"""The TypeScript frontend: the TypeScript compiler in a Node child, its records read back as JSON."""

from __future__ import annotations

from meizel.allowances import Policy
from meizel.graph.model import Code, Sources
from meizel.graph.universe import Universe
from meizel.language.file_scan import FileScan
from meizel.language.frontend import Frontend
from meizel.language.typescript.adapter import scan_source, typescript_extensions, typescript_files
from meizel.language.typescript.cache import scan_typescript_cached
from meizel.language.typescript.forms import DYNAMIC_ATTR_FORMS, EXTERNAL_FORMS

__all__ = ["TYPESCRIPT"]


def _owns(path: str, policy: Policy) -> bool:
    return path.endswith(typescript_extensions(policy))


def _scan(
    universe: Universe, paths: list[str], sources: Sources, _jobs: int | None, policy: Policy
) -> dict[str, FileScan]:
    return scan_typescript_cached(universe, paths, sources, policy)


def _scan_source(
    universe: Universe, path: str, source: bytes, sources: Sources, policy: Policy
) -> FileScan:
    return scan_source(universe, path, source, sources, policy=policy)


TYPESCRIPT = Frontend(
    "typescript",
    _owns,
    typescript_files,
    _scan,
    _scan_source,
    EXTERNAL_FORMS,
    DYNAMIC_ATTR_FORMS,
    Code.RESTRICTED_TS,
    "TypeScript",
    "write the dependency statically (a literal import specifier, named re-exports, ambient "
    "declarations in a .d.ts file) and pass an imported collaborator in instead of rewriting it",
)
