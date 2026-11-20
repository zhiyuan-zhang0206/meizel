"""The shape of a language frontend: what the checker asks of the code that reads one language."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from meizel.allowances import Policy
from meizel.graph.model import Code, Diagnostic, KindName, Sources
from meizel.graph.universe import Universe
from meizel.language.file_scan import FileScan

__all__ = ["Frontend", "StateKinds"]

# The process state a repository keeps, as its manifests declare it under `[state]`: directory, then
# file, then the kinds of state the file holds.
type StateKinds = Mapping[str, Mapping[str, tuple[KindName, ...]]]


@dataclass(frozen=True, slots=True)
class Frontend:
    name: str
    # Whether a path is a file of this language, under the policy the run reads.
    owns: Callable[[str, Policy], bool]
    # The files of this language the checker judges in a whole-tree run.
    files: Callable[[Universe, Policy], Sequence[str]]
    # The records of the given files of this language.
    scan: Callable[[Universe, list[str], Sources, int | None, Policy], dict[str, FileScan]]
    # What a scan of this language's files is told to treat as an ambient source: the state the
    # repository keeps, and the readers the policy lists, as this language spells them. A source
    # the language cannot spell is empty.
    sources: Callable[[StateKinds, Policy, Universe], Sources]
    # The readers the policy lists that this language no longer finds; only a whole run knows.
    stale_readers: Callable[[Universe, Policy], list[Diagnostic]]
    # The record of one file's text, as if it were the file at `path` (a version not in the tree).
    scan_source: Callable[[Universe, str, bytes, Sources, Policy], FileScan]
    # The restricted forms (`FileScan.restricted`) a file of this language may use once `[external]`
    # declares that it runs code from outside the repository, and once `[dynamic-attrs]` declares
    # that it owns an attribute name only the running program knows.
    external_forms: frozenset[str]
    dynamic_attr_forms: frozenset[str]
    # How a restricted form of this language is reported: the code (a debt of the file's directory),
    # the name of the subset the form is outside of, and what to do about a form in the directory
    # whose manifest is given.
    restricted_code: Code
    restricted_subset: str
    restricted_hint: Callable[[str, str], str]
