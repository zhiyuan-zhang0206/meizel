"""Which pytest fixtures are impure, and which tests of strict modules request them.

A fixture is impure when its own body reaches the world (an impure call, a module that is not pure, an
ambient read, an impure module's name) or when it requests an impure fixture; a test of strict modules
that requests one is reported. The standard-library tables the verdict reads are `purity.py`'s."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from meizel.graph.model import Code, Diagnostic, FactKind
from meizel.language.file_scan import FileScan
from meizel.language.frontend import RunView
from meizel.language.python.fixtures import (
    DEFAULT_IMPURE_FIXTURES,
    FixtureFunction,
    FixtureIndex,
)
from meizel.language.python.purity import (
    ALLOWED_STDLIB_MODULES,
    DEFAULT_IMPURE_CALLS,
    IMPURE_DOTTED_STDLIB_MODULES,
    IMPURE_STDLIB_MODULES,
)
from meizel.language.python.record import python_record
from meizel.language.python.resolve import PythonModules, python_modules
from meizel.language.test_files import is_test_file

__all__ = ["impure_fixture_diagnostics"]


def _build_fixture_index(
    scans: Mapping[str, FileScan], universe: PythonModules | None = None
) -> FixtureIndex:
    records = {path: python_record(scan) for path, scan in scans.items()}
    defined = {
        p: r.fixtures.defs | r.imported
        for p, r in records.items()
        if r.fixtures.defs or p.endswith("conftest.py") or r.fixtures.plugins
    }
    plugins = {
        p: [n for n, _ in r.fixtures.plugins] for p, r in records.items() if r.fixtures.plugins
    }
    return FixtureIndex(universe, defined, plugins)


def _is_module_impure(
    mod_name: str,
    index: FixtureIndex,
    purity_of: Callable[[str], str],
    pure_third_party: frozenset[str],
) -> bool:
    top = mod_name.split(".", 1)[0]
    if index.universe is not None and (
        index.universe.is_first_party_name(top)
        or index.universe.resolve_module(mod_name) is not None
    ):
        mod = index.universe.resolve_module(mod_name)
        return purity_of(mod.file) == "none" if mod and mod.file else False
    parts = mod_name.split(".")
    for i in range(len(parts), 0, -1):
        if ".".join(parts[:i]) in IMPURE_DOTTED_STDLIB_MODULES:
            return True
    if top in IMPURE_STDLIB_MODULES:
        return True
    return False if top in ALLOWED_STDLIB_MODULES else top not in pure_third_party


def _has_impure_fact(fn: FixtureFunction, scan: FileScan, purity_of: Callable[[str], str]) -> bool:
    for fact in scan.facts:
        if fact.kind == FactKind.IMPORT:
            target = fact.dst
            if not is_test_file(target) and purity_of(target) == "none":
                base = target.rpartition("/")[2].removesuffix(".py")
                if base in fn.names_loaded or any(sym in fn.names_loaded for sym in fact.names):
                    return True
    return False


def _is_function_direct_impure(
    fn: FixtureFunction,
    scan: FileScan,
    index: FixtureIndex,
    purity_of: Callable[[str], str],
    pure_third_party: frozenset[str],
) -> bool:
    if fn.is_async and fn.registered is not None:
        return True
    if any(c in DEFAULT_IMPURE_CALLS for c in fn.callees):
        return True
    if any(_is_module_impure(m, index, purity_of, pure_third_party) for m in fn.imported_modules):
        return True
    if any(fn.line <= a.line <= fn.end_line for a in scan.ambient):
        return True
    return _has_impure_fact(fn, scan, purity_of)


def _infer_helper_taint(
    scan: FileScan,
    index: FixtureIndex,
    purity_of: Callable[[str], str],
    pure_third_party: frozenset[str],
) -> set[str]:
    impure = {
        h.name
        for h in python_record(scan).fixtures.helpers
        if _is_function_direct_impure(h, scan, index, purity_of, pure_third_party)
    }
    changed = True
    while changed:
        changed = False
        for h in python_record(scan).fixtures.helpers:
            if h.name not in impure and any(c in impure for c in h.local_calls):
                impure.add(h.name)
                changed = True
    return impure


def _collect_file_fixtures(
    path: str,
    scan: FileScan,
    index: FixtureIndex,
    purity_of: Callable[[str], str],
    pure_third_party: frozenset[str],
) -> tuple[dict[tuple[str, str], FixtureFunction], set[tuple[str, str]]]:
    file_fixtures: dict[tuple[str, str], FixtureFunction] = {}
    direct: set[tuple[str, str]] = set()
    helper_impure = _infer_helper_taint(scan, index, purity_of, pure_third_party)
    for fn in python_record(scan).fixtures.functions:
        if fn.registered is not None:
            key = (path, fn.registered)
            file_fixtures[key] = fn
            if _is_function_direct_impure(fn, scan, index, purity_of, pure_third_party) or any(
                c in helper_impure for c in fn.local_calls
            ):
                direct.add(key)
    return file_fixtures, direct


def _propagate_fixture_taint(
    all_fixtures: Mapping[tuple[str, str], FixtureFunction],
    impure: set[tuple[str, str]],
    index: FixtureIndex,
    builtins_impure: frozenset[str],
) -> None:
    changed = True
    while changed:
        changed = False
        for (path, name), fn in all_fixtures.items():
            if (path, name) in impure:
                continue
            if any(
                r in builtins_impure or any((c, r) in impure for c in index.candidates(r, path)[0])
                for r in fn.requests
            ):
                impure.add((path, name))
                changed = True


def _infer_impure_fixtures(
    index: FixtureIndex,
    scans: Mapping[str, FileScan],
    purity_of: Callable[[str], str],
    pure_third_party: frozenset[str],
    external_impure_fixtures: frozenset[str] = frozenset(),
) -> frozenset[tuple[str, str]]:
    all_fixtures: dict[tuple[str, str], FixtureFunction] = {}
    direct_impure: set[tuple[str, str]] = set()
    for path, scan in scans.items():
        if is_test_file(path) or "fixture" in path or path.endswith("conftest.py"):
            f, d = _collect_file_fixtures(path, scan, index, purity_of, pure_third_party)
            all_fixtures.update(f)
            direct_impure.update(d)
    builtins = DEFAULT_IMPURE_FIXTURES | external_impure_fixtures
    impure = set(direct_impure)
    _propagate_fixture_taint(all_fixtures, impure, index, builtins)
    return frozenset(impure)


def _is_impure_fixture_request(
    name: str,
    test_path: str,
    impure_fixtures: frozenset[tuple[str, str]],
    index: FixtureIndex,
    external_impure: frozenset[str] = frozenset(),
) -> bool:
    if name in DEFAULT_IMPURE_FIXTURES or name in external_impure:
        return True
    return any((c, name) in impure_fixtures for c in index.candidates(name, test_path)[0])


# The tests of strict modules that request an impure fixture: the fixtures are judged over every
# scan of the run, the requests of the judged tests alone.
def impure_fixture_diagnostics(view: RunView) -> list[Diagnostic]:
    scans: dict[str, FileScan] = dict(view.scans)
    judged_scans = list(view.judged)
    for scan in judged_scans:
        scans.setdefault(scan.path, scan)
    index = _build_fixture_index(
        scans, None if view.universe is None else python_modules(view.universe)
    )
    pure_third_party = frozenset(view.policy.names("purity", "pure-third-party"))
    external_impure = DEFAULT_IMPURE_FIXTURES | frozenset(
        view.policy.names("purity", "impure-fixtures")
    )
    impure_fixtures = _infer_impure_fixtures(
        index, scans, view.purity_of, pure_third_party, external_impure_fixtures=external_impure
    )
    found: list[Diagnostic] = []
    for scan in judged_scans:
        if not is_test_file(scan.path):
            continue
        mode = view.test_mode(scan)
        if mode == "none":
            continue
        found.extend(
            Diagnostic(
                scan.path,
                request.line,
                Code.IMPURE_TEST_FIXTURE,
                f"test of strict modules requests impure fixture `{request.name}`",
                (
                    "pass pure values or fakes directly instead of requesting heavy I/O fixtures or monkeypatch",
                ),
                view.debt_key(scan.path, f"fixture {request.name}", mode),
            )
            for request in python_record(scan).fixtures.requests
            if _is_impure_fixture_request(
                request.name, scan.path, impure_fixtures, index, external_impure
            )
        )
    return found
