"""The rules the Python frontend judges Python files by, beyond what one file's scan decides: the
`TYPE_CHECKING` blocks, the readings spent as identity, and the impure fixtures a test requests."""

from __future__ import annotations

from collections.abc import Collection, Iterable

from meizel.allowances import Policy
from meizel.graph.model import Code, Diagnostic
from meizel.language.file_scan import FileScan
from meizel.language.frontend import RunView
from meizel.language.python.judge.fixture_purity import impure_fixture_diagnostics
from meizel.language.python.record import python_record
from meizel.language.python.scanner import TYPE_CHECKING_MESSAGE
from meizel.roles import select_packages

__all__ = [
    "python_rules",
    "type_checking_in_scope",
    "type_checking_lines",
    "type_checking_violations",
]


_WRAPPER_HINTS = (
    "why: a private function that is only `return time.monotonic()` hides the clock read from the "
    "rule on functions that wait and is a seam only a patch can reach; the module never hands it "
    "on, so nothing can inject the clock",
    "instead: take the clock as a required `Timers` parameter (or `now: float`) from the root, and "
    "delete the wrapper; one the module passes on as a default or an argument is an injection point",
    "see: meizel/docs/checker/fake-entropy.md",
)
_ENTROPY_HINTS = (
    "why: a monotonic or perf-counter reading, an object address and a process-local counter are "
    "not entropy: two processes started together draw the same value, a restart repeats it and an "
    "address is reused; and because they are neither the wall clock nor a random call they hide a "
    "read of randomness from `ambient-read`",
    "instead: entropy has one carrier, the process's `random.Random`: pass it down from the "
    "composition root and mint identifiers with `new_uuid(rng)`; keep an interval clock for "
    "durations (`end - start`); a module's clock is a required `Timers` parameter, not a private "
    "wrapper",
    "see: meizel/docs/checker/fake-entropy.md",
)


# A reading spent as identity or randomness, or a private wrapper over an interval clock. It is
# recordable debt like an ambient read, except in a strict file.
def _entropy_diagnostics(scans: Iterable[FileScan], view: RunView) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    for scan in scans:
        entropy = python_record(scan).entropy
        if not entropy or not view.governed(scan.path):
            continue
        mode = view.purity_of(scan.path)
        for site in entropy:
            reading, _, context = site.what.partition(" in ")
            what = (
                f"`{site.what.split()[-1]}` wraps an interval clock that nothing injects"
                if site.what.startswith("interval-wrapper")
                else f"`{reading}` is spent as identity or randomness ({context})"
            )
            debt = view.debt_key(scan.path, site.what, mode)
            hints = _WRAPPER_HINTS if site.what.startswith("interval-wrapper") else _ENTROPY_HINTS
            found.append(Diagnostic(scan.path, site.line, Code.FAKE_ENTROPY, what, hints, debt))
    return found


def type_checking_in_scope(path: str, packages: tuple[str, ...]) -> bool:
    if path == "conftest.py":
        return True
    return (
        path.endswith(".py")
        and not path.rsplit("/", 1)[-1].startswith("test_")
        and path.split("/", 1)[0] in packages
    )


# The lines of a Python scan that open a `TYPE_CHECKING` block: what `type_checking_violations` judges.
def type_checking_lines(scan: FileScan) -> tuple[int, ...]:
    return python_record(scan).type_checking


def type_checking_violations(
    lines: tuple[int, ...],
    rel_path: str,
    allowed: Collection[str],
    packages: tuple[str, ...],
) -> list[tuple[int, str]]:
    if rel_path in allowed or not type_checking_in_scope(rel_path, packages):
        return []
    return [(line, TYPE_CHECKING_MESSAGE) for line in lines]


def _type_checking_diagnostics(
    scans: Iterable[FileScan], roles: dict[str, tuple[str, ...]] | None, policy: Policy
) -> list[Diagnostic]:
    packages = select_packages(
        roles or {}, "application", "standalone", "tooling", "templates", "tests"
    )
    allowed = policy.reasons("type-checking", "files")
    return [
        Diagnostic(scan.path, line, Code.TYPE_CHECKING, message)
        for scan in scans
        for line, message in type_checking_violations(
            python_record(scan).type_checking, scan.path, allowed, packages
        )
    ]


# What the Python frontend judges of the files this run judges: `TYPE_CHECKING` blocks, readings spent
# as entropy and the impure fixtures a test of strict modules requests.
def python_rules(view: RunView) -> list[Diagnostic]:
    judged = list(view.judged)
    found = _entropy_diagnostics(judged, view)
    found.extend(_type_checking_diagnostics(judged, dict(view.roles), view.policy))
    found.extend(impure_fixture_diagnostics(view))
    return found
