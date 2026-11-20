# The Python frontend's reading of the policy's ambient sources: the state a repository keeps, the
# readers `[ambient-readers]` lists and every spelling a module gives them by re-exporting, and the
# readers that no longer exist. A reader is spelled as a Python module path (`pkg.module.name()`),
# so resolving one is the Python frontend's work; the checker only receives the `Sources` it makes.

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Iterable, Mapping

from meizel.allowances import POLICY, Policy
from meizel.graph.imports import Scope, collect_scope
from meizel.graph.model import (
    READER_CALL_MARK,
    READERS_RULE,
    Code,
    Diagnostic,
    KindName,
    MeizelError,
    Sources,
    Unless,
)
from meizel.graph.universe import Universe
from meizel.language.frontend import StateKinds
from meizel.language.python.bindings import module_bindings
from meizel.language.python.cache import (
    cached_module_imports,
    load_cached_sources,
    store_cached_sources,
)
from meizel.lint_common import is_test_path

__all__ = ["python_sources", "stale_readers"]

_CALL_MARK = READER_CALL_MARK
_READERS = READERS_RULE


def _module_of(directory: str, file: str) -> str:
    stem = file.rsplit(".", 1)[0]
    parts = [*directory.split("/"), *([] if stem == "__init__" else [stem])]
    return ".".join(part for part in parts if part)


def _state_digest(state: StateKinds) -> str:
    entries = [
        [directory, [[file, list(kinds)] for file, kinds in sorted(files.items())]]
        for directory, files in sorted(state.items())
        if files
    ]
    return hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()


# The state a repository keeps: modules that declare `[state]`, and the policy's names for it.
def python_sources(state: StateKinds, policy: Policy, universe: Universe) -> Sources:
    cache_key, cached = load_cached_sources(universe, _state_digest(state), policy)
    if cached is not None:
        return cached
    names: dict[str, KindName] = {}
    calls: dict[str, KindName] = {}
    for directory, files in state.items():
        for file, kinds in files.items():
            module = _module_of(directory, file)
            for kind in kinds:
                for name in policy.names("ambient", kind):
                    if name.endswith(_CALL_MARK):
                        calls[f"{module}.{name.removesuffix(_CALL_MARK)}"] = kind
                    else:
                        names[f"{module}.{name}"] = kind
    parsed: dict[str, dict[str, str]] = {}
    calls.update(_followed(universe, _readers(policy, call=True), parsed))
    readers = _followed(universe, _readers(policy, call=False), parsed)
    names.update(readers)
    result = Sources(names, calls, frozenset(readers), _spared(universe, policy))
    store_cached_sources(universe, cache_key, result)
    return result


# The policy's reader entries as `dotted name -> kind`: the calls (`name()`) or the bare names, which
# acquire where they are imported or read as an attribute.
def _readers(policy: Policy, *, call: bool) -> dict[str, KindName]:
    return {
        name.removesuffix(_CALL_MARK): kind
        for kind in policy.reader_kinds
        for name in policy.reasons(_READERS, kind)
        if name.endswith(_CALL_MARK) == call
    }


# The `unless` clause of one entry: the parameter, and where it sits among the arguments that can
# be given by position. The reason the clause cannot be read - no such module, not a module-level
# function, no such parameter - comes back as text instead, for the stale-reader diagnostic.
def _unless(universe: Universe, target: str, parameter: str) -> Unless | str:
    located = _locate(universe, target)
    if located is None:
        return "names no tracked module"
    _, file, member = located
    if len(member) != 1:
        return f"is a method: `unless` is read for a module-level function only, in {file}"
    functions = [
        node
        for node in ast.parse(universe.repo.load_text(file)).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == member[0]
    ]
    if not functions:
        return f"is not a module-level function of {file}"
    arguments = functions[-1].args
    positional = [argument.arg for argument in (*arguments.posonlyargs, *arguments.args)]
    if parameter in positional:
        return Unless(parameter, positional.index(parameter))
    if any(argument.arg == parameter for argument in arguments.kwonlyargs):
        return Unless(parameter, None)
    return f"names no parameter {parameter!r}"


# The readers whose read a passed parameter spares, by the name a call spells them: the clause is a
# property of the entry, so a re-exported spelling keeps it only where the policy lists that
# spelling. Entries whose clause cannot be read are left to `stale_readers`.
def _spared(universe: Universe, policy: Policy) -> dict[str, Unless]:
    found: dict[str, Unless] = {}
    for kind in policy.reader_kinds:
        for name, parameter in policy.unless_for(_READERS, kind).items():
            target = name.removesuffix(_CALL_MARK)
            resolved = _unless(universe, target, parameter)
            if isinstance(resolved, Unless):
                found[universe.context_for_module(target).canonical_name(target)] = resolved
    return found


# The module that defines a dotted reader: its dotted name, its file and the member path below it
# (`name` or `Class.method`). The longest prefix that names a tracked module wins.
def _locate(universe: Universe, target: str) -> tuple[str, str, tuple[str, ...]] | None:
    context = universe.context_for_module(target)
    parts = target.split(".")
    for end in range(len(parts) - 1, 0, -1):
        dotted = ".".join(parts[:end])
        module = context.resolve_module(dotted)
        if module is not None and module.file is not None:
            return context.canonical_name(dotted), module.file, tuple(parts[end:])
    return None


# How a module defines a top-level name: "function", "class" or "value" (an assignment); None when
# it does so some other way. The last definition wins, as it does at run time.
def _definition(universe: Universe, file: str, name: str) -> str | None:
    found: str | None = None
    for node in ast.parse(universe.repo.load_text(file)).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            found = "function"
        elif isinstance(node, ast.ClassDef) and node.name == name:
            found = "class"
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                found = "value"
    return found


# An entry is written the way its target is used: `name()` for a function, a class or a method (a
# call), `name` for a value. The other spelling would match nothing, and `stale-reader` is the one
# place that notices.
def _spelling_problem(
    universe: Universe, file: str, member: tuple[str, ...], target: str, *, call: bool
) -> str | None:
    if len(member) != 1:
        return None if call else f"`{'.'.join(member)}` is a method: list it as `{target}()`"
    (name,) = member
    kind = _definition(universe, file, name)
    if call and kind == "value":
        return f"`{name}` is a value, not a callable: list it as `{target}`, without `()`"
    if not call and kind == "function":
        return f"`{name}` is a function: list it as `{target}()`"
    return None


# Why a reader can no longer be found, or None when the module that the policy names defines it:
# a `def`, a class or an assignment there, or a method of a class there, spelled as it is used. A
# name the module only imports is not a definition: a function that moved leaves a re-export
# behind, and a call imported from the new place would no longer be seen.
def _missing_reader(universe: Universe, target: str, *, call: bool) -> str | None:
    located = _locate(universe, target)
    if located is None:
        return "names no tracked module"
    module, file, member = located
    bindings = module_bindings(universe, file)
    head = member[0]
    if bindings.dynamic:
        return None
    if len(member) == 1 and head in bindings.defined:
        return _spelling_problem(universe, file, member, target, call=call)
    if len(member) == 1:
        if head in bindings.imported:
            return f"`{head}` is imported by {file}, not defined there; list the module that defines it"
        return f"`{head}` is not defined in {file}"
    cls = next((facts for facts in bindings.classes if facts.name == head), None)
    if cls is None:
        return f"names no module `{module}.{head}` and no class `{head}` in {file}"
    if len(member) == 2 and member[1] in cls.methods:
        return _spelling_problem(universe, file, member, target, call=call)
    return f"class `{head}` in {file} defines no `{'.'.join(member[1:])}`"


# A listed reader that no longer exists fails, like any other stale allowance; only a
# whole-repository run knows.
def stale_readers(universe: Universe, policy: Policy) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    moved = ("remove the entry, or fix the name if the function moved",)
    clause = ("fix the parameter name, or drop the `unless` clause",)
    for kind in policy.reader_kinds:
        spared = policy.unless_for(_READERS, kind)
        for name in policy.reasons(_READERS, kind):
            target = name.removesuffix(_CALL_MARK)
            problem = _missing_reader(universe, target, call=name.endswith(_CALL_MARK))
            hint = moved
            if problem is None and name in spared:
                resolved = _unless(universe, target, spared[name])
                problem = resolved if isinstance(resolved, str) else None
                hint = clause
            if problem is not None:
                found.append(
                    Diagnostic(
                        POLICY,
                        policy.line_of(name),
                        Code.STALE_READER,
                        f"[{_READERS}.{kind}] {name!r} {problem}",
                        hint,
                    )
                )
    return found


_REEXPORT_HOPS = 12


# The names a module binds by importing, as `local name -> dotted origin`; an unparsable file binds none.
def _imports(universe: Universe, path: str) -> dict[str, str]:
    text = universe.repo.load_text(path)
    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError):
        return {}
    scope = Scope(None, canonicalize=universe.context(path).canonical_name)
    collect_scope(scope, tree.body, path.split("/")[:-1], walrus=":=" in text)
    return scope.imports


type _Spellings = dict[str, dict[str, KindName]]


# What can be re-exported, by its dotted origin: `module.name` -> {tail: kind}, where the tail is
# the method path below it (empty for a function).
def _origins(universe: Universe, readers: Mapping[str, KindName]) -> _Spellings:
    exported: _Spellings = {}
    for target, kind in readers.items():
        located = _locate(universe, target)
        if located is not None:
            module, _, member = located
            exported.setdefault(f"{module}.{member[0]}", {})[".".join(member[1:])] = kind
    return exported


# One round: every module among `candidates` that imports a known origin spells it under its own
# name too. Returns whether a new spelling appeared.
def _spread(
    universe: Universe,
    candidates: Iterable[str],
    exported: _Spellings,
    parsed: dict[str, dict[str, str]],
) -> bool:
    ordered = sorted(candidates)
    missing = [path for path in ordered if path not in parsed]
    if missing:
        parsed.update(cached_module_imports(universe, missing, _imports))
    grew = False
    for path in ordered:
        module = _module_of(*path.rpartition("/")[::2])
        for local, origin in parsed[path].items():
            for tail, kind in list(exported.get(origin, {}).items()):
                spelled = exported.setdefault(f"{module}.{local}", {})
                if tail not in spelled:
                    spelled[tail] = kind
                    grew = True
    return grew


# The readers and every spelling a module gives them by importing them at its top level: a call
# through a re-export is still the call of the reader. Only the non-test sources that mention one
# of the names are read, so the cost follows the readers, not the repository.
def _followed(
    universe: Universe,
    readers: Mapping[str, KindName],
    parsed: dict[str, dict[str, str]] | None = None,
) -> dict[str, KindName]:
    exported = _origins(universe, readers)
    repo = universe.repo
    seen: set[str] = set()
    candidates: set[str] = set()
    known = {} if parsed is None else parsed
    for _ in range(_REEXPORT_HOPS + 1):
        tokens = {origin.rpartition(".")[2] for origin in exported} - seen
        seen |= tokens
        candidates.update(p for p in repo.grep_words(tokens, ".py") if not is_test_path(p))
        if not _spread(universe, candidates, exported, known):
            break
    else:
        raise MeizelError(
            f"the re-exports of the listed readers need more than {_REEXPORT_HOPS} rounds of "
            "the scan to follow (a chain of 12 modules is always followed); list the module "
            "that defines the reader instead"
        )
    return {
        f"{origin}.{tail}" if tail else origin: kind
        for origin, tails in exported.items()
        for tail, kind in tails.items()
    }
