"""`debt sites`: every place in the source that a code that names a target is reported.

The baselines count violations per file and key; they do not say where. A codemod that removes
one kind of patch, and a design that needs the list of its sites, ask the source: this scans the
files and lists each patch with its file, line, form and target, optionally for the targets under
some prefixes. It reports what the source holds now, whether or not the baseline records it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from meizel.contracts.ambient_read import in_scope
from meizel.contracts.analysis import load_policy, scan_all
from meizel.contracts.debt import PATCH_CODES
from meizel.contracts.manifest import Manifest
from meizel.graph.model import Code, MeizelError, Sources, WorldReadSite, WorldReadWrapper
from meizel.graph.universe import Universe
from meizel.language import FileScan, enabled_frontends
from meizel.lint_common import is_test_path

__all__ = [
    "Approval",
    "Site",
    "approved",
    "format_approved",
    "format_sites",
    "propagation",
    "sites",
    "target_under",
]


# Whether the dotted `target` is `prefix` or inside it (`lib.mod` holds `lib.mod.f`, not `lib.mod2`).
def target_under(target: str, prefix: str) -> bool:
    return target == prefix or target.startswith((f"{prefix}.", f"{prefix}/"))


@dataclass(frozen=True, slots=True)
class Site:
    path: str
    line: int
    code: str
    form: str
    target: str


def _code(name: str) -> Code:
    codes = ", ".join(c.value for c in PATCH_CODES)
    for code in PATCH_CODES:
        if code.value == name:
            return code
    raise MeizelError(f"{name!r}: no sites are listed for this code; the codes are {codes}")


def _within(path: str, scopes: list[str]) -> bool:
    return not scopes or any(path == s or path.startswith(f"{s.rstrip('/')}/") for s in scopes)


def sites(
    universe: Universe,
    code: str,
    prefixes: Sequence[str],
    paths: list[str],
    jobs: int | None = None,
) -> list[Site]:
    """The sites of `code` whose target is under one of the prefixes (any, when none is given).

    Sorted by target, then file and line, so the same tree always lists the same way.
    """
    wanted = _code(code)
    scopes = [p.rstrip("/") for p in paths]
    found: list[Site] = []
    policy, problems = load_policy(universe)
    if problems:
        raise MeizelError(problems[0].render())
    files = [
        p
        for frontend in enabled_frontends(policy)
        for p in frontend.candidates(universe)
        if _within(p, scopes)
    ]
    for path, scan in sorted(scan_all(universe, Sources(), jobs, files, policy=policy).items()):
        found.extend(
            Site(path, patch.line, wanted.value, patch.form, patch.target)
            for patch in scan.patches
            if patch.code is wanted
            and (not prefixes or any(target_under(patch.target, prefix) for prefix in prefixes))
        )
    return sorted(found, key=lambda s: (s.target, s.path, s.line, s.form))


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def format_sites(found: list[Site], *, as_json: bool) -> str:
    if as_json:
        return json.dumps([asdict(site) for site in found], indent=2)
    lines = [f"{s.path}:{s.line}: {s.form} {s.target}" for s in found]
    files = len({s.path for s in found})
    lines.append(f"meizel: {_count(len(found), 'site')} in {_count(files, 'file')}")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Approval:
    path: str
    sites: int
    why: str


# The files the policy approves to patch, each with its reason and the patches it holds now. These
# are not debt and no manifest records them: this is the list a reviewer reads to see them grow.
def approved(universe: Universe, jobs: int | None = None) -> list[Approval]:
    policy, problems = load_policy(universe)
    if problems:
        raise MeizelError(problems[0].render())
    listed = policy.reasons("approved-patches", "files")
    present = [path for path in listed if path in universe.files]
    scans = scan_all(universe, Sources(), jobs, present, policy=policy)
    return [
        Approval(path, len(scans[path].patches) if path in scans else 0, why)
        for path, why in sorted(listed.items())
    ]


def format_approved(found: list[Approval], *, as_json: bool) -> str:
    if as_json:
        return json.dumps([asdict(item) for item in found], indent=2)
    lines = [f"{item.path}: {_count(item.sites, 'site')} -- {item.why}" for item in found]
    total = sum(item.sites for item in found)
    lines.append(
        f"meizel: {_count(total, 'patch site')} in {_count(len(found), 'approved file')}, not recorded as debt"
    )
    return "\n".join(lines)


# `ambient-read` records the point of acquisition: the file that calls `os.geteuid()`, `time.time()`
# or a `[state]` name. It does not follow the value out of that function, so a caller of
# `ensure_private_dir()` that hands it no `euid` inherits the world read and records nothing -- and
# neither does a caller above it. This is the measurement of that surface, and it writes nothing: no
# baseline, total or ratchet reads it, and the count it prints is an upper bound (a call that does
# pass the value cannot be told apart syntactically and is counted too).


@dataclass(frozen=True, slots=True)
class _Propagation:
    sites: list[WorldReadSite]
    wrappers: list[WorldReadWrapper]

    # The measurement as lines: the count, the widest wrappers, then every site. The first line says
    # what the number is, because it is the one line somebody quotes later.
    def render(self, *, top: int) -> str:
        inherited = sum(1 for wrapper in self.wrappers if not wrapper.acquires)
        lines = [
            f"meizel: world reads that travel through a function: {len(self.sites)} sites "
            f"(upper bound: a call that passes the value counts too; not in the ledger) "
            f"reaching {len(self.wrappers)} functions, {inherited} of them only by calling another"
        ]
        if not self.sites:
            lines.append("meizel: no production call reaches a function that acquires the world")
            return "\n".join(lines)
        lines.append(f"meizel: the {min(top, len(self.wrappers))} widest:")
        lines.extend(
            f"meizel: {wrapper.sites:5d}  {wrapper.path}:{wrapper.line}  {wrapper.name}"
            f"{'' if wrapper.acquires else '  (through a call)'}"
            for wrapper in self.wrappers[:top]
        )
        lines.append("meizel: the sites:")
        lines.extend(f"meizel: {site.path}:{site.line}  -> {site.wrapper}" for site in self.sites)
        return "\n".join(lines)


# The governed production files this measurement reads: a file declared under `[roots]` reads by
# design -- that is what a composition root is for -- so what leaves it was handed down on purpose,
# and a test records no acquisition at all.
def _measured_files(manifests: Mapping[str, Manifest], scans: Mapping[str, FileScan]) -> list[str]:
    roots = {
        f"{owner}/{path}" if owner else path for owner, m in manifests.items() for path in m.roots
    }
    return [
        path
        for path in sorted(scans)
        if path not in roots and not is_test_path(path) and in_scope(path, manifests)
    ]


# The world reads a call site inherits through a function, and where they enter the governed code.
def propagation(
    universe: Universe, manifests: Mapping[str, Manifest], scans: Mapping[str, FileScan]
) -> _Propagation:
    policy, _ = load_policy(universe)
    files = _measured_files(manifests, scans)
    reads = [frontend.world_reads(universe, files, scans) for frontend in enabled_frontends(policy)]
    return _Propagation(
        sorted((s for each in reads for s in each.sites), key=lambda site: (site.path, site.line)),
        sorted(
            (w for each in reads for w in each.wrappers),
            key=lambda wrapper: (-wrapper.sites, wrapper.name),
        ),
    )
