"""The shape of a language frontend: what the checker asks of the code that reads one language."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from meizel.allowances import Policy
from meizel.graph.model import Sources
from meizel.graph.universe import Universe
from meizel.language.file_scan import FileScan

__all__ = ["Frontend"]


@dataclass(frozen=True, slots=True)
class Frontend:
    name: str
    # Whether a path is a file of this language, under the policy the run reads.
    owns: Callable[[str, Policy], bool]
    # The files of this language the checker judges in a whole-tree run.
    files: Callable[[Universe, Policy], Sequence[str]]
    # The records of the given files of this language.
    scan: Callable[[Universe, list[str], Sources, int | None, Policy], dict[str, FileScan]]
    # The record of one file's text, as if it were the file at `path` (a version not in the tree).
    scan_source: Callable[[Universe, str, bytes, Sources, Policy], FileScan]
