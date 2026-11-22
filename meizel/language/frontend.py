"""The shape of a language frontend: what the checker asks of the code that reads one language."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from meizel.allowances import Policy
from meizel.graph.model import (
    Code,
    DebtKey,
    Diagnostic,
    Fact,
    ItemReads,
    KindName,
    PurityItem,
    Sources,
    WorldReads,
)
from meizel.graph.universe import Universe
from meizel.language.file_scan import FileScan

__all__ = ["Frontend", "RunView", "StateKinds"]

# The process state a repository keeps, as its manifests declare it under `[state]`: directory, then
# file, then the kinds of state the file holds.
type StateKinds = Mapping[str, Mapping[str, tuple[KindName, ...]]]


# What a frontend's rules are told of a run: the records of every file it read (the whole run's,
# whatever the language), the ones this run judges, and the answers only the checker's manifests
# can give -- how pure a path is declared to be, which files the ambient-read rule governs, and
# the debt a violation of a given file is recorded as.
@dataclass(frozen=True, slots=True)
class RunView:
    universe: Universe | None
    policy: Policy
    scans: Mapping[str, FileScan]
    judged: Sequence[FileScan]
    # The files a `check --changed` run was given; None for a whole-repository run.
    changed: frozenset[str] | None
    # The top-level roles the root manifest declares.
    roles: Mapping[str, tuple[str, ...]]
    # The purity a path is declared to have: "strict", "ratchet" or "off".
    purity_of: Callable[[str], str]
    # The purity a test file is judged under, from its own path and the modules it reaches.
    test_mode: Callable[[FileScan], str]
    # Whether the ambient-read rule governs the file (the roles whose code ships).
    governed: Callable[[str], bool]
    # The debt a violation `what` in `path` is recorded as under a purity: None where that is strict.
    debt_key: Callable[[str, str, str], DebtKey | None]


@dataclass(frozen=True, slots=True)
class Frontend:
    name: str
    # The file names that open a directory as a module (`__init__.py`, `index.ts`), the suffixes of
    # this language's source files, and whether a name beginning with an underscore is the language's own
    # protocol (`__init__`) rather than private to its directory.
    door_files: frozenset[str]
    # The files that run when their directory is imported (`__init__.py`); a language that imports
    # no directory has none.
    package_inits: frozenset[str]
    extensions: tuple[str, ...]
    protocol_name: Callable[[str], bool]
    # How a run's coverage names this language: the key of its count in a report, and the phrase after
    # the count in the summary line.
    coverage_key: str
    coverage_phrase: str
    # What this language reads of a repository, for the warning of a declaration no file it reads can
    # use; and what a reader can do about it in `where` (None when nothing).
    reads_scope: Callable[[Policy], str]
    scope_advice: Callable[[str], str | None]
    # Whether a path is a file of this language, under the policy the run reads.
    owns: Callable[[str, Policy], bool]
    # Every tracked file of this language, whatever the policy scopes, and the files of it the checker
    # judges in a whole-tree run.
    candidates: Callable[[Universe], Sequence[str]]
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
    # The facts this language adds to the run beyond those of its files' records, and the problems
    # in reading them (a whole-run question: the files of the judged paths only, when `changed`).
    facts: Callable[[RunView], tuple[list[Fact], list[Diagnostic]]]
    # The rules of this language that need more than one file's record, or the manifests.
    rules: Callable[[RunView], list[Diagnostic]]
    # The files a run that read only some files must read as well, scanned through the callable it is
    # handed, for the judgments above to see what they reach; the records it returns join the run's.
    companions: Callable[
        [Universe, Mapping[str, FileScan], Callable[[list[str]], dict[str, FileScan]]],
        dict[str, FileScan],
    ]
    # The lines `explain` adds about the files under a node: what this language's scan saw there.
    evidence: Callable[[Universe, Mapping[str, FileScan], str], list[str]]
    # The files of this language that import, however far, a changed file: None when one of them
    # cannot be read.
    impacted: Callable[[Universe, Sequence[str], int | None], frozenset[str] | None]
    # The directories of the independently packaged projects this language reads, and the problems of
    # their metadata (an error when a project cannot be read).
    projects: Callable[[Universe], tuple[str, ...]]
    # The world reads that travel through the functions of the given files, from the acquisitions of
    # their records.
    world_reads: Callable[[Universe, Sequence[str], Mapping[str, FileScan]], WorldReads]
    # What this language reads of a call recorded as an impure effect, from its name alone.
    item_reads: Callable[[PurityItem], ItemReads]
    # How a restricted form of this language is reported: the code (a debt of the file's directory),
    # the name of the subset the form is outside of, and what to do about a form in the directory
    # whose manifest is given.
    restricted_code: Code
    restricted_subset: str
    restricted_hint: Callable[[str, str], str]
