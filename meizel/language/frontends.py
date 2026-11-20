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

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from meizel.allowances import Policy
from meizel.graph.model import MeizelError, Sources
from meizel.graph.universe import Universe
from meizel.language.scan import FileScan
from meizel.language.scan_cache import scan_python_cached, scan_typescript_cached
from meizel.language.typescript import typescript_extensions, typescript_files

__all__ = ["FRONTENDS", "Frontend", "enabled_frontends", "scan_all"]


@dataclass(frozen=True, slots=True)
class Frontend:
    name: str
    # Whether a path is a file of this language, under the policy the run reads.
    owns: Callable[[str, Policy], bool]
    # The files of this language the checker judges in a whole-tree run.
    files: Callable[[Universe, Policy], Sequence[str]]
    # The records of the given files of this language.
    scan: Callable[[Universe, list[str], Sources, int | None, Policy], dict[str, FileScan]]


def _python_owns(path: str, _policy: Policy) -> bool:
    return path.endswith(".py")


def _python_files(universe: Universe, _policy: Policy) -> Sequence[str]:
    return universe.python_files


def _typescript_owns(path: str, policy: Policy) -> bool:
    return path.endswith(typescript_extensions(policy))


def _scan_typescript(
    universe: Universe, paths: list[str], sources: Sources, _jobs: int | None, policy: Policy
) -> dict[str, FileScan]:
    return scan_typescript_cached(universe, paths, sources, policy)


PYTHON = Frontend("python", _python_owns, _python_files, scan_python_cached)
TYPESCRIPT = Frontend("typescript", _typescript_owns, typescript_files, _scan_typescript)
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
