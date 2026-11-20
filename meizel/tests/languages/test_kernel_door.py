"""The checker's kernel reads a language only through `meizel.language`'s door (the frontends)."""

from __future__ import annotations

import ast
from pathlib import Path

_KERNEL = ("contracts", "graph")
# The record a frontend keeps of a file (`FileScan.extra`) is its own: no kernel module names its
# type or reads the field.
_NATIVE_NAMES = frozenset({"PythonRecord", "python_record", "decode_record", "encode_record"})


def _kernel_trees() -> dict[str, ast.Module]:
    root = Path(__file__).resolve().parents[2]
    return {
        path.relative_to(root).as_posix(): ast.parse(path.read_text())
        for directory in _KERNEL
        for path in sorted((root / directory).rglob("*.py"))
        if "/tests/" not in path.relative_to(root).as_posix()
    }


def _imported_modules(tree: ast.Module) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def _reaching(frontend: str) -> set[str]:
    return {
        path
        for path, tree in _kernel_trees().items()
        if any(m == frontend or m.startswith(f"{frontend}.") for m in _imported_modules(tree))
    }


def test_the_kernel_imports_no_frontend_code() -> None:
    assert _reaching("meizel.language.python") == set()
    assert _reaching("meizel.language.typescript") == set()


def test_the_kernel_never_reads_a_frontends_own_record_of_a_file() -> None:
    reading = {
        path
        for path, tree in _kernel_trees().items()
        for node in ast.walk(tree)
        if (isinstance(node, ast.Attribute) and node.attr == "extra")
        or (isinstance(node, ast.Name) and node.id in _NATIVE_NAMES)
        or (isinstance(node, ast.alias) and node.name in _NATIVE_NAMES)
    }
    assert reading == set()


def test_the_graph_package_reads_no_syntax_tree() -> None:
    reading = {
        path
        for path, tree in _kernel_trees().items()
        if path.startswith("graph/") and "ast" in _imported_modules(tree)
    }
    assert reading == set()
