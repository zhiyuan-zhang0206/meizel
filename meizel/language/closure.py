"""What the frontends say of the files a change reaches."""

from __future__ import annotations

from collections.abc import Sequence

from meizel.allowances import Policy
from meizel.graph.universe import Universe
from meizel.language.frontends import enabled_frontends

__all__ = ["reverse_closure"]


# The files that import, however far, one of the `changed` files, over every enabled language: None
# when a language could not read one of its files.
def reverse_closure(
    universe: Universe, policy: Policy, changed: Sequence[str], jobs: int | None = None
) -> frozenset[str] | None:
    reached: set[str] = set()
    for frontend in enabled_frontends(policy):
        found = frontend.impacted(universe, changed, jobs)
        if found is None:
            return None
        reached |= found
    return frozenset(reached)
