# `ambient-read`: only a composition root reaches the world a process runs in.
#
# A file that takes the clock, an interval clock, the environment, the home or working directory, the
# platform, a process id, randomness, or the process state the repository keeps (the kinds its policy
# declares under `[ambient]`) instead of being handed it is a decision that cannot be tested by
# value. The files that may do so are declared under `[roots]` in their directory's `meizel.toml`,
# each with the kinds it may acquire; every other acquisition in non-test code is a violation.
# Recorded like any other, a violation can be carried as debt except where the file is `strict`.

from __future__ import annotations

from collections.abc import Iterable, Mapping

from meizel.contracts.debt import file_key
from meizel.contracts.manifest import Manifest, effective_purity, unlicensed
from meizel.contracts.policy import POLICY, Policy
from meizel.graph.model import (
    OS_KINDS,
    READER_CALL_MARK,
    READERS_RULE,
    Acquisition,
    AmbientKind,
    Code,
    DebtKey,
    Diagnostic,
    KindName,
    Sources,
    covered_kinds,
)
from meizel.graph.universe import Universe
from meizel.language import FileScan, ambient_sources, frontend_of

__all__ = [
    "ambient_diagnostics",
    "reader_problems",
    "sources_from",
    "stale_roots",
]

_NO_POLICY = Policy()
_CALL_MARK = READER_CALL_MARK
_READERS = READERS_RULE
# The roles whose source code is governed: what ships, the runnable templates and the tooling.
_GOVERNED_ROLES = ("application", "standalone", "templates", "tooling", "frontend")
_WHAT: dict[str, str] = {
    AmbientKind.ENVIRON: "the environment",
    AmbientKind.CLOCK: "the clock",
    AmbientKind.MONOTONIC: "an interval clock",
    AmbientKind.HOME: "the home directory",
    AmbientKind.CWD: "the working directory",
    AmbientKind.PLATFORM: "the platform",
    AmbientKind.PID: "the process identity",
    AmbientKind.RANDOM: "randomness",
    AmbientKind.ARGV: "the command line",
    AmbientKind.FILESYSTEM: "the contents of files",
    AmbientKind.SLEEP: "a wait",
}
# The three lines every ambient-read carries: the principle, the recipe and the rule.
_WHY = (
    "why: code that reads the world itself cannot be tested by handing it a value, and it answers "
    "differently on another machine or at another time; the world is read once, in the process's "
    "composition root, and passed down"
)
_INSTEAD_HELD = (
    "instead: take the handle or the config from the composition root as a required parameter or "
    "a field of a frozen config; only a root builds it"
)
_INSTEAD_STDLIB = (
    "instead: read it in the composition root and pass the value down; a decision in the middle "
    "becomes a pure function of its inputs"
)
_SEE = (
    "see: docs/conventions/python-conventions.md#composition-roots-and-required-dependencies; "
    "a file is declared a root under [roots] in its directory's meizel.toml, and only if it is one"
)


# The state a repository keeps (the modules that declare `[state]`) and the readers its policy lists,
# as each enabled frontend spells them.
def sources_from(manifests: Mapping[str, Manifest], policy: Policy, universe: Universe) -> Sources:
    state = {directory: manifest.state for directory, manifest in manifests.items()}
    return ambient_sources(state, policy, universe)


# Whether the rule governs this file: a governed top-level role (tests record no acquisitions).
def in_scope(path: str, manifests: Mapping[str, Manifest]) -> bool:
    root = manifests.get("")
    if root is None:
        return False
    top = path.split("/", 1)[0]
    return any(top in root.roles.get(role, ()) for role in _GOVERNED_ROLES)


def _diagnostic(scan: FileScan, acquisition: Acquisition, mode: str, owner: str) -> Diagnostic:
    kind, target = acquisition.kind, acquisition.target
    instead = _INSTEAD_STDLIB if kind in OS_KINDS else _INSTEAD_HELD
    what = _WHAT[kind] if kind in OS_KINDS else f"the `{kind}` state the repository keeps"
    debt = (
        None if mode == "strict" else DebtKey(owner, file_key(owner, scan.path, f"{kind} {target}"))
    )
    return Diagnostic(
        scan.path,
        acquisition.line,
        Code.AMBIENT_READ,
        f"reads {what} (`{target}`) outside a composition root",
        (_WHY, instead, _SEE),
        debt,
    )


# Every acquisition in a governed file whose directory manifest does not declare its kind -- and every
# `[debt.impure-call]` entry that pays for the same call the declaration licenses (`unlicensed`): the
# read a root makes is one fact, so the ledger states it once.
def ambient_diagnostics(
    scans: Iterable[FileScan], manifests: Mapping[str, Manifest]
) -> list[Diagnostic]:
    scanned = list(scans)
    found: list[Diagnostic] = []
    for scan in scanned:
        if not scan.ambient or not in_scope(scan.path, manifests):
            continue
        owner, _, name = scan.path.rpartition("/")
        manifest = manifests.get(owner)
        allowed = frozenset[KindName]() if manifest is None else manifest.licensed_kinds(name)
        mode = effective_purity(scan.path, manifests)
        found.extend(
            _diagnostic(scan, acquisition, mode, owner)
            for acquisition in scan.ambient
            if acquisition.kind not in allowed
        )
    found.extend(_legal_calls_recorded(manifests, scanned))
    return found


# The `[debt.impure-call]` entries this run leaves unrecorded because `[roots]` licenses the call: one
# read declared twice, kept as a number `debt prune` drops. This note is the only trace of the drop,
# so it names the entry; it records a counting correction, not a repayment -- the code still calls.
def _legal_calls_recorded(
    manifests: Mapping[str, Manifest], scans: Iterable[FileScan]
) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    for scan in scans:
        owner = scan.path.rpartition("/")[0]
        manifest = manifests.get(owner)
        if manifest is None or not manifest.debt:
            continue
        rows = manifest.debt.get(Code.IMPURE_CALL, {})
        kept = {item.key for item in unlicensed(manifests, scan)}
        for item in scan.purity:
            key = file_key(owner, scan.path, item.key)
            if item.code is not Code.IMPURE_CALL or item.key in kept or key not in rows:
                continue
            found.append(
                Diagnostic(
                    manifest.path,
                    manifest.debt_line(Code.IMPURE_CALL, key),
                    Code.LEGAL_READ_RECORDED,
                    f"[roots] licenses `{item.key}` in {scan.path!r}, and the entry records that "
                    "call as debt",
                    (
                        "delete the entry: one read cannot be licensed by [roots] and paid for as "
                        "debt at once; `debt prune` drops it, and this is a counting correction, "
                        "not a repayment",
                    ),
                )
            )
    return found


# A declared root kind that its file no longer acquires; only a whole run can know. `filesystem` and
# `sleep` derive no acquisition, so they are acquired where the purity rule charges a call of them: a
# root of either kind whose file makes no such call is stale like any other, and a declaration cannot
# outlive the code.
def stale_roots(
    scans: Mapping[str, FileScan], manifests: Mapping[str, Manifest]
) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    for directory, manifest in sorted(manifests.items()):
        for name, root in manifest.roots.items():
            path = f"{directory}/{name}" if directory else name
            scan = scans.get(path)
            if scan is None:
                continue
            reads = frontend_of(path, _NO_POLICY).item_reads
            acquired = {acquisition.kind for acquisition in scan.ambient}.union(
                *(reads(item).door for item in scan.purity)
            )
            found.extend(
                Diagnostic(
                    manifest.path,
                    manifest.line_of(name),
                    Code.STALE_ROOT,
                    f"[roots] {name!r} declares `{kind}` but the file no longer acquires it",
                    ("remove the kind from [roots]; a root declares what it reads, not more",),
                )
                for kind in root.kinds
                if not acquired.intersection(covered_kinds(kind))
            )
    return found


# The shape of the policy's `[ambient-readers.<kind>]` entries: a fully qualified call
# (`pkg.module.name()`, `pkg.module.Class.method()`) or name (`pkg.module.NAME`), listed under
# exactly one kind.
def reader_problems(policy: Policy) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    seen: set[str] = set()
    for kind in policy.reader_kinds:
        for name in policy.reasons(_READERS, kind):
            where = f"[{_READERS}.{kind}] {name!r}"
            line = policy.line_of(name)
            if "." not in name.removesuffix(_CALL_MARK):
                message = (
                    f"{where} must be qualified, as in `pkg.module.name()` or `pkg.module.NAME`"
                )
            elif name in seen:
                message = f"{where} is listed under more than one kind: a reader has one kind"
            else:
                seen.add(name)
                continue
            found.append(Diagnostic(POLICY, line, Code.POLICY_SYNTAX, message))
    for kind in policy.reader_kinds:
        for name in policy.unless_for(_READERS, kind):
            if name.endswith(_CALL_MARK):
                continue
            message = (
                f"[{_READERS}.{kind}] {name!r} is not a call: `unless` spares the read a call "
                f"makes, so list it as `{name}()` or drop the clause"
            )
            found.append(Diagnostic(POLICY, policy.line_of(name), Code.POLICY_SYNTAX, message))
    return found
