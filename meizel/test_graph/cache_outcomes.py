from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from xml.etree import ElementTree

from meizel.test_graph.cache_plan import TestPlan

__all__ = ["ShadowReport", "outcomes_from_junit", "recordable_tests", "shadow_report"]


# How each test file of a run ended, from its junit reports (`junit_family=xunit1` names the file of
# a case; otherwise the longest dotted prefix of the case's class that names a test file does). A
# file failed if any case failed or errored, passed if a case passed and none failed, and was
# skipped otherwise; a file no report names is absent.
def outcomes_from_junit(texts: Iterable[str], tests: Collection[str]) -> dict[str, str]:
    by_module = {test.removesuffix(".py").replace("/", "."): test for test in tests}
    seen: dict[str, set[str]] = {}
    for text in texts:
        for case in ElementTree.fromstring(text).iter("testcase"):  # noqa: S314
            owner = _case_file(case, tests, by_module)
            if owner is None:
                continue
            verdict = "passed"
            for child in case:
                if child.tag in {"failure", "error"}:
                    verdict = "failed"
                    break
                if child.tag == "skipped":
                    verdict = "skipped"
            seen.setdefault(owner, set()).add(verdict)
    return {
        owner: "failed" if "failed" in verdicts else "passed" if "passed" in verdicts else "skipped"
        for owner, verdicts in sorted(seen.items())
    }


def _case_file(
    case: ElementTree.Element, tests: Collection[str], by_module: Mapping[str, str]
) -> str | None:
    named = (case.get("file") or "").removeprefix("./")
    if named in tests:
        return named
    classname = case.get("classname") or ""
    if not classname and (name := case.get("name") or "") in tests:
        return name
    parts = classname.split(".")
    for end in range(len(parts), 0, -1):
        if (owner := by_module.get(".".join(parts[:end]))) is not None:
            return owner
    return None


# The tests whose result a run may record: those it passed and the plan gave a key.
def recordable_tests(plan: TestPlan, outcomes: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(t for t in sorted(plan.keys) if outcomes.get(t) == "passed")


@dataclass(frozen=True, slots=True)
class ShadowReport:
    would_skip: int
    would_skip_passed: int
    would_skip_failed: tuple[str, ...]
    would_skip_not_run: tuple[str, ...]
    uncacheable: dict[str, int] = field(default_factory=dict[str, int])
    unbounded: dict[str, int] = field(default_factory=dict[str, int])
    saved_seconds: float = 0.0

    def as_json(self) -> str:
        return json.dumps(
            {
                "would_skip": self.would_skip,
                "would_skip_passed": self.would_skip_passed,
                "would_skip_failed": list(self.would_skip_failed),
                "would_skip_not_run": list(self.would_skip_not_run),
                "uncacheable": self.uncacheable,
                "unbounded": self.unbounded,
                "saved_seconds": self.saved_seconds,
            },
            indent=2,
            sort_keys=True,
        )


def _by_reason(reasons: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reason in reasons:
        head = reason.partition(":")[0]
        counts[head] = counts.get(head, 0) + 1
    return counts


# A plan set against how the tests actually ended. `would_skip_failed` is the soundness measure: a
# test the cache would have skipped that failed when it ran, which must stay empty.
def shadow_report(
    plan: TestPlan, outcomes: Mapping[str, str], durations: Mapping[str, float] | None = None
) -> ShadowReport:
    passed = [t for t in plan.skippable if outcomes.get(t) == "passed"]
    return ShadowReport(
        would_skip=len(plan.skippable),
        would_skip_passed=len(passed),
        would_skip_failed=tuple(t for t in plan.skippable if outcomes.get(t) == "failed"),
        would_skip_not_run=tuple(t for t in plan.skippable if t not in outcomes),
        uncacheable=_by_reason(plan.uncacheable.values()),
        unbounded=_by_reason(plan.unbounded.values()),
        saved_seconds=sum((durations or {}).get(t, 0.0) for t in passed),
    )
