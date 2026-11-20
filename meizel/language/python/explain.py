"""What `meizel explain` says of the Python files under a node: the lists a function appends to and
the fixture request chains of the tests there."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from meizel.graph.universe import Universe
from meizel.language.file_scan import FileScan
from meizel.language.python.fixtures import FixtureFunction, FixtureIndex, FixtureRequest
from meizel.language.python.record import python_record

__all__ = ["python_evidence"]


@dataclass(frozen=True, slots=True)
class _FixtureContext:
    index: FixtureIndex
    scans: Mapping[str, FileScan]
    test_path: str


@dataclass(frozen=True, slots=True)
class _Display:
    lines: tuple[str, ...]
    remaining: int
    truncated: bool = False


# What a Python file's scan saw under `node`: the lists a function appends to and the fixture request
# chains of its tests.
def python_evidence(universe: Universe, scans: Mapping[str, FileScan], node: str) -> list[str]:
    selected = {
        path: scan
        for path, scan in scans.items()
        if (path == node or not node or path.startswith(f"{node}/")) and path.endswith(".py")
    }
    if not selected:
        return []
    lines = [
        "Python source evidence (non-gating; no runtime execution or semantic purity proof):",
        "  input list observations cover direct append on builtin-list annotations with no local rebinding observed;",
        "  aliases, fields, nested scopes and other mutations are not resolved; absence is not a no-mutation proof.",
    ]
    for path, scan in sorted(selected.items()):
        lines.extend(
            f"  {path}:{item.line} {item.function}: {item.parameter}.append(...) "
            "on a list-annotated parameter (syntax; runtime type/execution unknown)"
            for item in python_record(scan).input_appends
        )
    lines.extend(_fixture_lines(universe, scans, selected))
    return lines


def _fixture_lines(
    universe: Universe, scans: Mapping[str, FileScan], selected: dict[str, FileScan]
) -> list[str]:
    records = {path: python_record(scan) for path, scan in scans.items()}
    index = FixtureIndex(
        universe,
        {path: record.fixtures.defs | record.imported for path, record in records.items()},
        {path: [name for name, _ in record.fixtures.plugins] for path, record in records.items()},
    )
    lines = [
        "  fixture request chains (declared syntax; resolved in the consuming test context):",
        "  class/nested requesters, autouse, module marks, imported fixture aliases and dynamic names",
        "  are not fully resolved; these chains are not a complete resource or static-admission assessment.",
    ]
    for path, scan in sorted(selected.items()):
        for function in python_record(scan).fixtures.functions:
            if function.registered is not None:
                continue
            label = f"{path}:{function.line} {function.name}"
            if not function.module_owned:
                lines.append(f"    {label}: unknown requester ownership (scope or module binding)")
                continue
            lines.extend(_test_requests(_FixtureContext(index, scans, path), function, label))
    return lines


def _test_requests(
    context: _FixtureContext,
    function: FixtureFunction,
    label: str,
) -> list[str]:
    roots = _owned_requests(context.scans[context.test_path], function)
    if not roots:
        return [f"    {label}: no explicit requests observed (implicit requests unknown)"]
    lines: list[str] = []
    remaining = 64
    for request in roots:
        result = _request_lines(context, request, (), [label], remaining)
        lines.extend(result.lines)
        remaining = result.remaining
        if result.truncated:
            lines.append(f"    {label}: display limit reached; additional request paths unknown")
            break
    return lines


def _owned_requests(scan: FileScan, function: FixtureFunction) -> list[FixtureRequest]:
    return [
        request
        for request in python_record(scan).fixtures.requests
        if request.requester_line == function.line
    ]


def _request_lines(
    context: _FixtureContext,
    request: FixtureRequest,
    active: tuple[tuple[str, FixtureFunction], ...],
    trail: list[str],
    remaining: int,
) -> _Display:
    if remaining == 0:
        return _Display((), 0, truncated=True)
    remaining -= 1
    trail = [*trail, f"{request.name} [{request.form}]"]
    function = _requester(context, request, active)
    problem = _request_problem(request, function, active)
    if problem is not None:
        return _Display((_render(trail, problem),), remaining)
    selected = _definition(context, request, active)
    if isinstance(selected, str):
        return _Display((_render(trail, selected),), remaining)
    path, definition = selected
    trail.append(f"{path}:{definition.line} {definition.name}")
    if any(path == p and definition.line == f.line for p, f in active):
        return _Display((_render(trail, "recursive definition; execution unknown"),), remaining)
    if len(active) >= 32:
        return _Display(
            (_render(trail, "display depth limit reached; remaining requests unknown"),), remaining
        )
    requests = _owned_requests(context.scans[path], definition)
    if not requests:
        return _Display(
            (_render(trail, "resolved explicit chain; implicit requests unknown"),), remaining
        )
    lines: list[str] = []
    for child in requests:
        result = _request_lines(context, child, (*active, (path, definition)), trail, remaining)
        lines.extend(result.lines)
        remaining = result.remaining
        if result.truncated:
            return _Display(tuple(lines), remaining, truncated=True)
    return _Display(tuple(lines), remaining)


def _requester(
    context: _FixtureContext,
    request: FixtureRequest,
    active: tuple[tuple[str, FixtureFunction], ...],
) -> FixtureFunction | None:
    if active:
        return active[-1][1]
    return next(
        (
            f
            for f in python_record(context.scans[context.test_path]).fixtures.functions
            if f.line == request.requester_line
        ),
        None,
    )


def _request_problem(
    request: FixtureRequest,
    function: FixtureFunction | None,
    active: tuple[tuple[str, FixtureFunction], ...],
) -> str | None:
    if request.form in {"lookup", "call"}:
        return "unknown receiver/execution; not a required fixture request"
    if request.form == "usefixtures" and active:
        return "marker on fixture definition; not a required request"
    if request.form == "parameter" and function is not None and not function.parameters_known:
        return "unknown parametrization: names or indirect mode not resolved"
    return None


def _definition(
    context: _FixtureContext,
    request: FixtureRequest,
    active: tuple[tuple[str, FixtureFunction], ...],
) -> tuple[str, FixtureFunction] | str:
    candidates, ambiguous = context.index.candidates(request.name, context.test_path)
    depth = sum(definition.registered == request.name for _, definition in active)
    if depth >= len(candidates):
        return "unresolved fixture or exhausted same-name override chain"
    path = candidates[depth]
    if path in ambiguous:
        return "unknown plugin registration order"
    definitions = [
        f
        for f in python_record(context.scans[path]).fixtures.functions
        if f.registered == request.name
    ]
    if len(definitions) != 1 or not definitions[0].module_owned:
        return f"unknown definition ownership in {path}"
    return path, definitions[0]


def _render(trail: list[str], result: str) -> str:
    return f"    {' -> '.join(trail)}: {result}"
