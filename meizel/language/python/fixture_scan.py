"""The pytest fixtures a Python file defines and requests, read from its syntax tree."""

from __future__ import annotations

import ast
from collections.abc import Callable

from meizel.language.python.fixtures import FixtureFunction, FixtureRequest, FixtureState

__all__ = ["fixture_name", "plugin_names", "record_call", "record_function"]

_FIXTURE_DECORATORS = frozenset({"pytest.fixture", "pytest_asyncio.fixture"})
_PARAMETRIZE = "pytest.mark.parametrize"
_PATCH_DECORATORS = {"unittest.mock.patch": 2, "unittest.mock.patch.object": 3}
_Dotted = Callable[[ast.expr], str | None]


def _string_args(call: ast.Call) -> list[str]:
    return [a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]


def fixture_name(node: ast.FunctionDef | ast.AsyncFunctionDef, dotted: _Dotted) -> str | None:
    """The name a `@pytest.fixture` function registers, or None for a plain function."""
    for deco in node.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        if dotted(target) not in _FIXTURE_DECORATORS:
            continue
        if isinstance(deco, ast.Call):
            for keyword in deco.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    return str(keyword.value.value)
        return node.name
    return None


def _defaultless(args: ast.arguments) -> list[str]:
    positional = [*args.posonlyargs, *args.args]
    required = positional[: len(positional) - len(args.defaults)]
    keyword = [a for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True) if d is None]
    return [a.arg for a in (*required, *keyword)]


def _parametrized(deco: ast.Call) -> set[str]:
    if any(k.arg == "indirect" for k in deco.keywords) or not deco.args:
        return set()
    first = deco.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return {n.strip() for n in first.value.split(",") if n.strip()}
    if isinstance(first, ast.List | ast.Tuple):
        return {
            e.value for e in first.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
        }
    return set()


def _patch_injected(deco: ast.Call, callee: str) -> bool:
    """Whether a `patch` decorator passes a mock as an argument (no explicit `new`)."""
    return len(deco.args) < _PATCH_DECORATORS[callee] and not any(
        k.arg == "new" for k in deco.keywords
    )


# Parameters that pytest resolves as fixtures.
def _requested_names(node: ast.FunctionDef | ast.AsyncFunctionDef, dotted: _Dotted) -> list[str]:
    params = _defaultless(node.args)
    excluded: set[str] = set()
    injected = 0
    for deco in node.decorator_list:
        if not isinstance(deco, ast.Call):
            continue
        callee = dotted(deco.func)
        if callee == _PARAMETRIZE:
            excluded |= _parametrized(deco)
        elif callee in _PATCH_DECORATORS and _patch_injected(deco, callee):
            injected += 1
    if params and params[0] in {"self", "cls"}:
        params = params[1:]
    return [p for p in params[injected:] if p not in excluded]


def _literal_registration(node: ast.FunctionDef | ast.AsyncFunctionDef, dotted: _Dotted) -> bool:
    for deco in node.decorator_list:
        if not isinstance(deco, ast.Call) or dotted(deco.func) not in _FIXTURE_DECORATORS:
            continue
        if deco.args:
            return False
        for keyword in deco.keywords:
            if keyword.arg is None:
                return False
            if keyword.arg == "name" and not (
                isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str)
            ):
                return False
    return True


def _parameters_known(node: ast.FunctionDef | ast.AsyncFunctionDef, dotted: _Dotted) -> bool:
    for deco in node.decorator_list:
        if not isinstance(deco, ast.Call) or dotted(deco.func) != _PARAMETRIZE:
            continue
        if any(keyword.arg is None for keyword in deco.keywords):
            return False
        indirect = next((k.value for k in deco.keywords if k.arg == "indirect"), None)
        if isinstance(indirect, ast.Constant) and indirect.value is True:
            continue
        if indirect is not None or not deco.args or not _literal_names(deco.args[0]):
            return False
    return True


def _literal_names(value: ast.expr) -> bool:
    if isinstance(value, ast.Constant):
        return isinstance(value.value, str)
    return isinstance(value, ast.List | ast.Tuple) and all(
        isinstance(item, ast.Constant) and isinstance(item.value, str) for item in value.elts
    )


def _inspect_call(
    child: ast.Call,
    dotted: _Dotted,
    reqs: list[str],
    callees: list[str],
    local_calls: list[str],
) -> None:
    d = dotted(child.func)
    if d:
        callees.append(d)
    if isinstance(child.func, ast.Name):
        local_calls.append(child.func.id)
    if (
        isinstance(child.func, ast.Attribute)
        and child.func.attr == "getfixturevalue"
        and child.args
        and isinstance(child.args[0], ast.Constant)
        and isinstance(child.args[0].value, str)
    ):
        reqs.append(child.args[0].value)


def _inspect_function_ast(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    dotted: _Dotted,
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    reqs = list(_requested_names(node, dotted))
    imported: list[str] = []
    callees: list[str] = []
    local_calls: list[str] = []
    names_loaded: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            imported.extend(a.name for a in child.names)
        elif isinstance(child, ast.ImportFrom) and child.module:
            imported.append(child.module)
            for a in child.names:
                imported.append(f"{child.module}.{a.name}")
        elif isinstance(child, ast.Call):
            _inspect_call(child, dotted, reqs, callees, local_calls)
        elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            names_loaded.append(child.id)
    return reqs, imported, callees, local_calls, names_loaded


def _record_fixture_entry(
    state: FixtureState,
    func_info: FixtureFunction,
    *,
    is_target: bool,
    is_helper: bool,
) -> None:
    if is_target:
        state.functions.append(func_info)
        for name in func_info.requests:
            state.requests.append(
                FixtureRequest(
                    name,
                    func_info.line,
                    skip_self=name == func_info.registered,
                    requester_line=func_info.line,
                )
            )
    elif is_helper:
        state.helpers.append(func_info)


def record_function(
    state: FixtureState,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    dotted: _Dotted,
    *,
    test_file: bool,
    top_level: bool,
    module_owned: bool,
) -> None:
    registered = fixture_name(node, dotted)
    if registered is not None:
        state.defs.add(registered)
    is_test = test_file and top_level and node.name.startswith("test")
    if registered is None and not is_test and not (test_file and top_level):
        return

    reqs, imported, callees, local_calls, names_loaded = _inspect_function_ast(node, dotted)
    func_info = FixtureFunction(
        node.name,
        node.lineno,
        registered,
        module_owned and _literal_registration(node, dotted),
        _parameters_known(node, dotted),
        end_line=getattr(node, "end_lineno", node.lineno),
        is_async=isinstance(node, ast.AsyncFunctionDef),
        requests=tuple(reqs),
        imported_modules=tuple(imported),
        callees=tuple(callees),
        local_calls=tuple(local_calls),
        names_loaded=tuple(names_loaded),
    )
    _record_fixture_entry(
        state,
        func_info,
        is_target=registered is not None or is_test,
        is_helper=test_file and top_level,
    )


def record_call(
    state: FixtureState,
    node: ast.Call,
    callee: str | None,
    *,
    requester: ast.FunctionDef | ast.AsyncFunctionDef | None,
) -> None:
    """`usefixtures("a")` and `request.getfixturevalue("a")` request by literal name."""
    owner = requester.lineno if requester is not None else 0
    marker = requester is not None and any(node is deco for deco in requester.decorator_list)
    if callee == "pytest.mark.usefixtures":
        for name in _string_args(node):
            state.requests.append(
                FixtureRequest(
                    name,
                    node.lineno,
                    requester_line=owner,
                    form="usefixtures" if marker else "call",
                )
            )
    elif isinstance(node.func, ast.Attribute) and node.func.attr == "getfixturevalue":
        for name in _string_args(node)[:1]:
            state.requests.append(
                FixtureRequest(name, node.lineno, requester_line=owner, form="lookup")
            )


def plugin_names(value: ast.expr) -> list[str] | None:
    """Literal `pytest_plugins` entries; None when the value is not a literal."""
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return [value.value]
    if isinstance(value, ast.List | ast.Tuple):
        names = [
            e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
        return names if len(names) == len(value.elts) else None
    return None
