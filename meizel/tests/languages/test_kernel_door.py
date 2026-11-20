"""The checker's kernel reads a language only through `meizel.language`'s door (the frontends)."""

from __future__ import annotations

import ast
from pathlib import Path

_KERNEL = ("contracts", "graph")
_FRONTENDS = ("meizel.language.python", "meizel.language.typescript")
# What still reaches into a frontend package, each to be removed by moving the judgment into the
# frontend: the list only shrinks.
_STILL_REACHING = frozenset({"contracts/analysis.py", "contracts/rule.py"})


def _reaching(root: Path) -> set[str]:
    found: set[str] = set()
    for directory in _KERNEL:
        for path in sorted((root / directory).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if "/tests/" in relative:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                modules = (
                    [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
                if any(m == f or m.startswith(f"{f}.") for m in modules for f in _FRONTENDS):
                    found.add(relative)
    return found


def test_kernel_reaches_into_no_more_frontend_code_than_the_listed_files() -> None:
    reaching = _reaching(Path(__file__).resolve().parents[2])
    assert reaching <= _STILL_REACHING, sorted(reaching - _STILL_REACHING)
    assert reaching == _STILL_REACHING, "a file stopped reaching a frontend: shrink the list"
