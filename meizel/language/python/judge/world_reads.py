"""The world reads that travel through Python functions.

`ambient-read` records the point of acquisition: the file that calls `os.geteuid()`, `time.time()` or
a `[state]` name. It does not follow the value out of that function, so a caller of
`ensure_private_dir()` that hands it no `euid` inherits the world read and records nothing -- and
neither does a caller above it. This reads the files' syntax trees for the functions that acquire
(from the acquisitions of their records) and the calls that reach them."""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence

from meizel.graph.model import WorldReads, WorldReadSite, WorldReadWrapper
from meizel.graph.universe import Universe
from meizel.language.file_scan import FileScan
from meizel.language.python.resolve import Scope, collect_scope, dotted_chain

__all__ = ["python_world_reads"]


# The dotted module a file defines (`pkg/mod.py` -> `pkg.mod`, `pkg/__init__.py` -> `pkg`).
def _dotted(path: str) -> str:
    parts = path.removesuffix(".py").split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _tree(universe: Universe, path: str) -> ast.Module | None:
    try:
        return ast.parse(universe.repo.load_text(path), filename=path)
    except (SyntaxError, ValueError):
        return None


# Every node of a module with the qualified name of the function that holds it, "" at module level:
# a class keeps its methods' names (`Class.method`), a nested function its outer's (`outer.inner`).
def _nodes(
    body: Sequence[ast.AST], prefix: str = "", current: str = ""
) -> Iterator[tuple[str, ast.AST]]:
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            name = f"{prefix}{node.name}"
            yield name, node
            yield from _nodes(node.body, f"{name}.", name)
        elif isinstance(node, ast.ClassDef):
            yield current, node
            yield from _nodes(node.body, f"{prefix}{node.name}.", current)
        else:
            yield current, node
            yield from _nodes(list(ast.iter_child_nodes(node)), prefix, current)


def _spans(tree: ast.Module) -> list[tuple[int, int, str]]:
    return [
        (node.lineno, node.end_lineno or node.lineno, name)
        for name, node in _nodes(tree.body)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _enclosing(spans: list[tuple[int, int, str]], line: int) -> str:
    inside = [span for span in spans if span[0] <= line <= span[1]]
    return min(inside, key=lambda span: span[1] - span[0])[2] if inside else ""


def _module_scope(tree: ast.Module, path: str) -> Scope:
    scope = Scope(None)
    collect_scope(scope, tree.body, path.split("/")[:-1], walrus=True)
    return scope


def _module_level(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }


def _callee(func: ast.expr, scope: Scope, module: str, defined: set[str]) -> str | None:
    chain = dotted_chain(func)
    if chain is None:
        return None
    base, attrs = chain
    origin, _ = scope.find(base.id)
    if origin is not None:
        return ".".join([origin, *attrs])
    return f"{module}.{base.id}" if not attrs and base.id in defined else None


def _read(
    universe: Universe, path: str, acquisitions: Iterable[int]
) -> tuple[dict[str, str], dict[str, tuple[str, int]], list[tuple[str, str, str, int]]]:
    tree = _tree(universe, path)
    if tree is None:
        return {}, {}, []
    module = _dotted(path)
    scope = _module_scope(tree, path)
    defined = _module_level(tree)
    spans = _spans(tree)
    holders = {
        f"{module}.{holder}"
        for holder in {_enclosing(spans, line) for line in acquisitions}
        if holder
    }
    found = {
        f"{module}.{name}": (path, node.lineno)
        for name, node in _nodes(tree.body)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    calls = [
        (f"{module}.{current}" if current else module, callee, path, node.lineno)
        for current, node in _nodes(tree.body)
        if isinstance(node, ast.Call)
        for callee in [_callee(node.func, scope, module, defined)]
        if callee is not None
    ]
    return dict.fromkeys(holders, path), found, calls


# The functions that reach an acquisition through calls: a function that calls one inherits its
# read, and so does the caller of that caller, at any depth.
def _closure(acquiring: set[str], calls: list[tuple[str, str, str, int]]) -> set[str]:
    inside = set(acquiring)
    edges: dict[str, set[str]] = {}
    for caller, callee, _, _ in calls:
        edges.setdefault(caller, set()).add(callee)
    changed = True
    while changed:
        changed = False
        for caller, callees in edges.items():
            if caller not in inside and not callees.isdisjoint(inside):
                inside.add(caller)
                changed = True
    return inside


# The world reads a call site inherits through a function, from the acquisitions of the records of `files`.
def python_world_reads(
    universe: Universe, files: Sequence[str], scans: Mapping[str, FileScan]
) -> WorldReads:
    paths = [path for path in files if path.endswith(".py")]
    acquiring: dict[str, str] = {}
    defined: dict[str, tuple[str, int]] = {}
    calls: list[tuple[str, str, str, int]] = []
    for path in paths:
        holders, functions, edges = _read(universe, path, (a.line for a in scans[path].ambient))
        acquiring.update(holders)
        defined.update(functions)
        calls.extend(edges)
    inside = _closure(set(acquiring), calls)
    sites = sorted(
        (
            WorldReadSite(path, line, callee)
            for caller, callee, path, line in calls
            if callee in inside and caller not in acquiring
        ),
        key=lambda site: (site.path, site.line),
    )
    counted = Counter(site.wrapper for site in sites)
    wrappers = sorted(
        (
            WorldReadWrapper(
                name, defined[name][0], defined[name][1], counted[name], name in acquiring
            )
            for name in inside
            if name in defined and counted[name]
        ),
        key=lambda wrapper: (-wrapper.sites, wrapper.name),
    )
    return WorldReads(sites, wrappers)
