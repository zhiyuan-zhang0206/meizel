"""Which TypeScript files the checker reads: every tracked source, and those the policy scopes."""

from __future__ import annotations

from meizel.allowances import Policy
from meizel.graph.universe import Universe
from meizel.language.typescript.compiler import load_ts_config

__all__ = [
    "typescript_candidates",
    "typescript_extensions",
    "typescript_files",
    "typescript_scopes",
]


# Every tracked TypeScript source file, declarations excluded, whatever the policy scopes.
def typescript_candidates(universe: Universe) -> tuple[str, ...]:
    return tuple(
        path
        for path in universe.files_ending((".ts", ".tsx", ".mts", ".cts"))
        if not path.endswith((".d.ts", ".d.mts", ".d.cts"))
    )


def typescript_files(universe: Universe, policy: Policy) -> tuple[str, ...]:
    config = load_ts_config(policy)
    active = (*config.scopes, *config.import_sources)
    return tuple(
        path
        for path in typescript_candidates(universe)
        if path.endswith(config.extensions)
        and (not active or any(path == p or path.startswith(f"{p}/") for p in active))
    )


# The extensions the policy reads as TypeScript (`[typescript].extensions`).
def typescript_extensions(policy: Policy) -> tuple[str, ...]:
    return tuple(load_ts_config(policy).extensions)


# The directories whose TypeScript behavior this repository judges (`[typescript].scopes`): the
# caller needs the list, not the whole config.
def typescript_scopes(policy: Policy) -> tuple[str, ...]:
    return load_ts_config(policy).scopes
