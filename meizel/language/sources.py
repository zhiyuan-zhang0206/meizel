"""What the frontends tell the checker about the ambient sources a repository declares."""

from __future__ import annotations

from meizel.allowances import Policy
from meizel.graph.model import Diagnostic, Sources
from meizel.graph.universe import Universe
from meizel.language.frontend import StateKinds
from meizel.language.frontends import enabled_frontends

__all__ = ["ambient_sources", "stale_readers"]


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
