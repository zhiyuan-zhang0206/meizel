"""The reverse Python import closure of a checkout named by its root path."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from meizel.checkout import load_universe
from meizel.language.python.resolve import python_reverse_closure

__all__ = ["python_reverse_closure_at"]


# Reverse Python import closure for a checkout root, returning None on any read or syntax error.
def python_reverse_closure_at(
    root: Path, changed_files: Sequence[str], *, jobs: int | None = None
) -> frozenset[str] | None:
    return python_reverse_closure(load_universe(root), changed_files, jobs=jobs)
