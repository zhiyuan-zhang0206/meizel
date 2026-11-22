"""The TypeScript frontend: the TypeScript compiler in a Node child, its records read back as JSON."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from meizel.allowances import Policy
from meizel.graph.model import (
    Code,
    Diagnostic,
    Fact,
    ItemReads,
    PurityItem,
    Sources,
    WorldReads,
)
from meizel.graph.universe import Universe
from meizel.language.file_scan import FileScan
from meizel.language.frontend import Frontend, RunView, StateKinds
from meizel.language.typescript.adapter import scan_source
from meizel.language.typescript.cache import scan_typescript_cached
from meizel.language.typescript.comments import (
    scan_typescript_comments,
    typescript_comment_files,
)
from meizel.language.typescript.files import (
    typescript_candidates,
    typescript_extensions,
    typescript_files,
    typescript_scopes,
)
from meizel.language.typescript.forms import DYNAMIC_ATTR_FORMS, EXTERNAL_FORMS, restricted_hint

__all__ = ["TYPESCRIPT"]


def _owns(path: str, policy: Policy) -> bool:
    return path.endswith(typescript_extensions(policy))


def _scan(
    universe: Universe, paths: list[str], sources: Sources, _jobs: int | None, policy: Policy
) -> dict[str, FileScan]:
    return scan_typescript_cached(universe, paths, sources, policy)


# The policy's readers are spelled as Python modules, and this scan reads no ambient source.
def _sources(_state: StateKinds, _policy: Policy, _universe: Universe) -> Sources:
    return Sources()


def _stale_readers(_universe: Universe, _policy: Policy) -> list[Diagnostic]:
    return []


# The TypeScript frontend adds no facts, has no rules of its own beyond what a record carries, reads
# no file beside the ones it is asked for, and has nothing of its own to say under `explain`.
def _facts(_view: RunView) -> tuple[list[Fact], list[Diagnostic]]:
    return [], []


def _rules(_view: RunView) -> list[Diagnostic]:
    return []


def _companions(
    _universe: Universe,
    _scans: Mapping[str, FileScan],
    _scan_more: Callable[[list[str]], dict[str, FileScan]],
) -> dict[str, FileScan]:
    return {}


def _evidence(_universe: Universe, _scans: Mapping[str, FileScan], _node: str) -> list[str]:
    return []


def _impacted(
    _universe: Universe, _changed: Sequence[str], _jobs: int | None
) -> frozenset[str] | None:
    return frozenset()


def _projects(_universe: Universe) -> tuple[str, ...]:
    return ()


def _world_reads(
    _universe: Universe, _files: Sequence[str], _scans: Mapping[str, FileScan]
) -> WorldReads:
    return WorldReads()


def _item_reads(_item: PurityItem) -> ItemReads:
    return ItemReads(frozenset(), frozenset())


def _scan_source(
    universe: Universe, path: str, source: bytes, sources: Sources, policy: Policy
) -> FileScan:
    return scan_source(universe, path, source, sources, policy=policy)


def _protocol_name(_child: str) -> bool:
    return False


def _reads_scope(policy: Policy) -> str:
    scopes = typescript_scopes(policy)
    covered = ", ".join(scopes) if scopes else "none declared"
    return f"the files inside [typescript].scopes ({covered})"


def _scope_advice(where: str) -> str | None:
    return (
        f"add {where} to the scopes so the TypeScript it names is read, unless a `.d.ts` "
        "declaration is all it names, which no scope can make readable"
    )


TYPESCRIPT = Frontend(
    "typescript",
    frozenset({"index.ts", "index.tsx", "index.mts", "index.cts"}),
    frozenset(),
    (".ts", ".tsx", ".mts", ".cts"),
    _protocol_name,
    "typescript_compiler_ast",
    "TypeScript files (compiler AST)",
    _reads_scope,
    _scope_advice,
    _owns,
    typescript_candidates,
    typescript_files,
    _scan,
    _sources,
    _stale_readers,
    _scan_source,
    EXTERNAL_FORMS,
    DYNAMIC_ATTR_FORMS,
    _facts,
    _rules,
    _companions,
    _evidence,
    _impacted,
    _projects,
    _world_reads,
    _item_reads,
    Code.RESTRICTED_TS,
    "TypeScript",
    restricted_hint,
    typescript_comment_files,
    scan_typescript_comments,
)
