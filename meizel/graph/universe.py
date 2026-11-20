# The node universe: tracked files, their directories, and module resolution.
#
# Data only. `meizel.checkout` builds one from a checkout, runs git for it, and reads the files the
# universe names; nothing here touches the filesystem.
# See meizel/docs/checker/purity.md.

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

__all__ = [
    "MANIFEST",
    "SOURCE_EXTENSIONS",
    "Checkout",
    "EditPlan",
    "SourceTree",
    "Universe",
    "is_private_module",
    "parent_of",
]

MANIFEST = "meizel.toml"
SOURCE_EXTENSIONS = (".py", ".ts", ".tsx", ".mts", ".cts")


# What a command decided to write, delete or create; `meizel.checkout.apply_plan` does it.
@dataclass(frozen=True, slots=True)
class EditPlan:
    writes: dict[Path, str] = field(default_factory=dict[Path, str])
    byte_writes: dict[Path, bytes] = field(default_factory=dict[Path, bytes])
    deletes: tuple[Path, ...] = ()
    dirs: tuple[Path, ...] = ()


_DUNDER_MODULE = re.compile(r"__\w+__(\.py)?")


def is_private_module(child: str) -> bool:
    """A module or package whose name starts with an underscore is private to its directory.

    A dunder name (`__init__.py`, `__main__.py`) is the language's own protocol, not a private one.
    """
    return child.startswith("_") and _DUNDER_MODULE.fullmatch(child) is None


def parent_of(path: str) -> str:
    return path.rpartition("/")[0]


# The filesystem a lint reads, as one value: the checkout's root, the predicates and readers that
# answer it, and the two readings only a checkout can take (Git's admitted names and the roles this
# repository declares). Every reading is a field holding a function, so this value decides nothing
# and reads nothing; `meizel.checkout.source_tree` binds `pathlib` to it where the checkout is owned
# and a test binds its own, which is what lets a deciding module ask which files to judge without
# holding the calls that answer. `root` binds the two listings and the relative arithmetic a caller
# does over them; every other field takes the path it is asked about, so a tree also answers for a
# directory outside its root. `tracked` is `meizel.checkout.tracked_files` bound to `root`: its
# keyword arguments (`include_untracked`, `regular`) stay the shell's.
# See meizel/docs/lint/lint-common-admission.md.
@dataclass(frozen=True, slots=True)
class SourceTree:
    root: Path
    is_file: Callable[[Path], bool]
    is_dir: Callable[[Path], bool]
    exists: Callable[[Path], bool]
    resolve: Callable[[Path], Path]
    lexists: Callable[[Path], bool]
    rglob: Callable[[Path, str], Iterator[Path]]
    read_bytes: Callable[[Path], bytes]
    tracked: Callable[..., list[str]]
    roles: Callable[[], Mapping[str, tuple[str, ...]]]
    run_node: Callable[[Path, str], tuple[int, str, str]] = field(
        default=lambda _producer, _payload: (1, "", "node runner not configured")
    )
    # The Node package whose compiler `run_node` starts the analyzer with, asked only when an analysis
    # needs it; None when the tree was bound without one, and then nothing checks that package's
    # install before node starts.
    toolchain: Callable[[], Path | None] = field(default=lambda: None)


# The checkout a decision layer works on: the root it reads and the files under it. The decision
# modules of `meizel/contracts` take this handle and never build one, so what they decide stays
# separable from the git and file reads that answer it; `meizel.checkout.GitRepo` is the one
# implementation, and it is the shell that runs git for the universe.
class Checkout(Protocol):
    @property
    def root(self) -> Path: ...

    # The same checkout as a value: the filesystem reads a deciding module may take, bound where the
    # checkout is owned, so a caller that only judges does not import the shell that runs git.
    @property
    def tree(self) -> SourceTree: ...

    def has_file(self, rel: str) -> bool: ...

    def load_text(self, rel: str, *, default: str | None = None) -> str: ...

    def load_bytes(self, rel: str) -> bytes: ...

    def run_text(self, *args: str) -> str: ...

    def run_bytes(self, *args: str, stdin: bytes | None = None) -> bytes: ...

    def default_base(self) -> str: ...

    def show_optional_text(self, ref: str, path: str) -> str | None: ...

    def show_bytes(self, ref: str, path: str) -> bytes: ...

    def stage_all(self) -> None: ...

    def apply_plan(self, plan: EditPlan) -> None: ...

    def grep_files(self, marker: str, suffixes: tuple[str, ...]) -> list[str]: ...

    def grep_words(self, words: Collection[str], suffix: str) -> list[str]: ...

    def untracked_files(self) -> tuple[str, ...]: ...

    def file_digests(self) -> dict[str, str]: ...

    def scanner_digest(self) -> str: ...

    def cache_get_many(self, keys: Collection[str]) -> dict[str, str]: ...

    def cache_put_many(self, entries: Mapping[str, str]) -> None: ...

    def memo_get(self, key: str) -> object | None: ...

    def memo_put(self, key: str, value: object) -> None: ...

    def universe(self) -> Universe: ...

    def checkout(self, ref: str) -> AbstractContextManager[Checkout]: ...


class Universe:
    """Tracked regular files and every directory above them: data, whatever the language."""

    DOOR_FILES: frozenset[str] = frozenset(
        {"__init__.py", "index.ts", "index.tsx", "index.mts", "index.cts"}
    )

    def __init__(self, repo: Checkout, tracked: list[str]) -> None:
        self.repo = repo
        self.root = repo.root
        self.files: frozenset[str] = frozenset(tracked)
        children: dict[str, set[str]] = {}
        for path in tracked:
            self._add_chain(children, path)
        self.dirs: frozenset[str] = frozenset(children)
        self.children: dict[str, tuple[str, ...]] = {
            directory: tuple(sorted(names)) for directory, names in children.items()
        }
        self.manifest_dirs: frozenset[str] = frozenset(
            parent_of(p) for p in tracked if p.rsplit("/", 1)[-1] == MANIFEST
        )
        self._digests: dict[str, str] | None = None
        self._memo: dict[str, object] = {}

    # A universe crosses into worker processes without what a language derived from it: the views
    # in `memo` are rebuilt where they are asked for.
    def __getstate__(self) -> dict[str, object]:
        return {key: value for key, value in self.__dict__.items() if key != "_memo"}

    def __setstate__(self, state: dict[str, object]) -> None:
        self.__dict__.update(state)
        self._memo = {}

    @staticmethod
    def _add_chain(children: dict[str, set[str]], path: str) -> None:
        children.setdefault("", set())
        parts = path.split("/")
        for depth in range(len(parts)):
            directory = "/".join(parts[:depth])
            name = parts[depth]
            if depth == len(parts) - 1 and name == MANIFEST:
                continue
            children.setdefault(directory, set()).add(name)
            if depth < len(parts) - 1:
                children.setdefault("/".join(parts[: depth + 1]), set())

    # The tracked files whose name ends in one of `suffixes`, sorted.
    def files_ending(self, suffixes: tuple[str, ...]) -> tuple[str, ...]:
        key = f"ending:{suffixes}"
        found = self._memo.get(key)
        if found is None:
            found = tuple(sorted(p for p in self.files if p.endswith(suffixes)))
            self._memo[key] = found
        return found if isinstance(found, tuple) else ()

    # What a language derives from this universe and keeps beside it, built once by `build`.
    def memo(self, key: str, build: Callable[[], object]) -> object:
        if key not in self._memo:
            self._memo[key] = build()
        return self._memo[key]

    def file_digests(self) -> dict[str, str]:
        if self._digests is None:
            self._digests = self.repo.file_digests()
        return self._digests
