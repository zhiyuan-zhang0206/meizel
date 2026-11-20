"""The language frontends: one per language the checker reads, each optional.

A frontend owns the files of its language and turns them into `FileScan` records: the facts (edges,
fixtures, loads), the purity items, the ambient acquisitions, the patches and the problems of each
file. Everything after that (manifests, the graph, recorded debt, the policy's exemptions, budgets)
reads those records and never the language, which is how two languages share one `check`, `debt
record` and `debt prune`. A repository chooses its languages under `[languages] enabled` in
`meizel.policy.toml`; without the table every built-in frontend runs. A frontend that runs out of
process speaks the same record as JSON (`encode_file_scan` / `decode_file_scan`), the form the
TypeScript frontend's results are cached in.
"""

from __future__ import annotations

from collections.abc import Sequence

from meizel import allowances
from meizel.allowances import Policy
from meizel.graph.model import MeizelError, Sources
from meizel.graph.universe import Universe
from meizel.language.file_scan import FileScan
from meizel.language.frontend import Frontend
from meizel.language.python import PYTHON
from meizel.language.typescript import TYPESCRIPT

__all__ = [
    "FRONTENDS",
    "enabled_frontends",
    "invalidate_policy_caches",
    "scan_all",
    "scan_source",
]

FRONTENDS = {frontend.name: frontend for frontend in (PYTHON, TYPESCRIPT)}


# The frontends a run uses, in the order the policy names them: every built-in one when the policy
# names none, and a refusal for a name no frontend answers to.
def enabled_frontends(policy: Policy) -> tuple[Frontend, ...]:
    names = policy.names("languages", "enabled")
    if not names:
        return tuple(FRONTENDS.values())
    unknown = sorted(set(names) - FRONTENDS.keys())
    if unknown:
        raise MeizelError(
            f"[languages] enabled names {', '.join(unknown)}; the frontends are "
            f"{', '.join(FRONTENDS)}"
        )
    return tuple(FRONTENDS[name] for name in dict.fromkeys(names))


# The records of a run: each enabled frontend scans its own files, the given paths when the caller
# names them and the whole tree's otherwise. A path no enabled frontend owns is not scanned.
def scan_all(
    universe: Universe,
    sources: Sources,
    jobs: int | None = None,
    paths: Sequence[str] | None = None,
    *,
    policy: Policy,
) -> dict[str, FileScan]:
    scans: dict[str, FileScan] = {}
    for frontend in enabled_frontends(policy):
        chosen = (
            list(frontend.files(universe, policy))
            if paths is None
            else [path for path in paths if frontend.owns(path, policy)]
        )
        if chosen:
            scans.update(frontend.scan(universe, chosen, sources, jobs, policy))
    return scans


# The record of `source` as if it were the file at `path` (a version that is not in the working
# tree): the frontend that owns the path reads it, and Python reads any path none owns.
def scan_source(
    universe: Universe, path: str, source: bytes, sources: Sources, *, policy: Policy
) -> FileScan:
    frontend = next((f for f in FRONTENDS.values() if f.owns(path, policy)), PYTHON)
    return frontend.scan_source(universe, path, source, sources, policy)


# This is the scanner boundary for a disposable snapshot whose policy has changed. Each cache
# owner invalidates its own entries; callers neither reach into private caches nor skip the
# original snapshot validation to avoid them.
def invalidate_policy_caches() -> None:
    allowances.invalidate_cache()
