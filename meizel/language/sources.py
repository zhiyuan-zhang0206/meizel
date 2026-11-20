"""What the frontends tell the checker about the ambient sources a repository declares."""

from __future__ import annotations

from meizel.allowances import Policy
from meizel.graph.model import Diagnostic, Sources
from meizel.graph.universe import Universe
from meizel.language.frontend import StateKinds
from meizel.language.frontends import FRONTENDS, enabled_frontends

__all__ = [
    "ambient_sources",
    "candidates_of",
    "projects",
    "source_candidates",
    "stale_readers",
]


# What a run's scans treat as ambient sources: each enabled frontend names its own, and the run
# reads their union.
def ambient_sources(state: StateKinds, policy: Policy, universe: Universe) -> Sources:
    found = [frontend.sources(state, policy, universe) for frontend in enabled_frontends(policy)]
    return Sources(
        {name: kind for each in found for name, kind in each.names.items()},
        {name: kind for each in found for name, kind in each.calls.items()},
        frozenset().union(*(each.uses for each in found)),
        {name: unless for each in found for name, unless in each.unless.items()},
    )


# The listed readers no enabled frontend finds any more.
def stale_readers(universe: Universe, policy: Policy) -> list[Diagnostic]:
    return [
        found
        for frontend in enabled_frontends(policy)
        for found in frontend.stale_readers(universe, policy)
    ]


# The directories of the independently packaged projects the enabled languages read.
def projects(universe: Universe, policy: Policy) -> list[str]:
    return [
        directory
        for frontend in enabled_frontends(policy)
        for directory in frontend.projects(universe)
    ]


# Every tracked source file of every built-in language, whatever the policy enables or scopes.
def source_candidates(universe: Universe) -> tuple[str, ...]:
    return tuple(path for frontend in FRONTENDS.values() for path in frontend.candidates(universe))


# Every tracked source file of the language named `name`.
def candidates_of(universe: Universe, name: str) -> tuple[str, ...]:
    return tuple(FRONTENDS[name].candidates(universe))
