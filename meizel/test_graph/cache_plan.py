from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from meizel.test_graph.cache_key import SCHEMA, CachePolicy, closure_digest, result_key
from meizel.test_graph.closure import InputClosure
from meizel.test_graph.model import TestGraphState, TestLanes

__all__ = ["PlanSettings", "TestPlan", "plan_tests"]


# What a plan is made for besides the tests: the lane and pytest arguments of the run, the
# environment and tool a key is made of, and what the repository's policy says about caching.
@dataclass(frozen=True, slots=True)
class PlanSettings:
    lane: str
    args: Sequence[str]
    environment: Mapping[str, str]
    tool: str
    policy: CachePolicy


@dataclass(frozen=True, slots=True)
class TestPlan:
    keys: dict[str, str]
    skippable: tuple[str, ...]
    run: tuple[str, ...]
    uncacheable: dict[str, str]
    unbounded: dict[str, str]

    def as_json(self) -> str:
        return json.dumps(
            {
                "schema": SCHEMA,
                "keys": self.keys,
                "skippable": list(self.skippable),
                "run": list(self.run),
                "uncacheable": self.uncacheable,
                "unbounded": self.unbounded,
            },
            indent=2,
            sort_keys=True,
        )


def _uncacheable_reason(
    test: str, lanes: TestLanes, state: TestGraphState, policy: CachePolicy
) -> str | None:
    if test in lanes.native:
        return f"native-lane:{dict(lanes.reasons).get(test, '')}"
    test_facts = state.facts.get(test)
    if test_facts is None:
        return "no-facts"
    held = sorted(set(test_facts.markers) & policy.uncacheable_markers)
    return f"marker:{held[0]}" if held else None


# Which of `tests` a recorded pass lets a run skip, and the key each is judged by. A test is never
# cached when its lane is native or it holds an `uncacheable` marker; one whose inputs the graph
# cannot bound is keyed by the whole tree. `passes` holds the keys of results recorded as passed.
def plan_tests(
    tests: Collection[str],
    state: TestGraphState,
    lanes: TestLanes,
    closures: Mapping[str, InputClosure],
    settings: PlanSettings,
    passes: Collection[str],
) -> TestPlan:
    keys: dict[str, str] = {}
    uncacheable: dict[str, str] = {}
    unbounded: dict[str, str] = {}
    skippable: list[str] = []
    memo: dict[frozenset[str], str] = {}
    for test in sorted(tests):
        reason = _uncacheable_reason(test, lanes, state, settings.policy)
        closure = closures.get(test)
        if reason is not None or closure is None:
            uncacheable[test] = reason or "no-closure"
            continue
        if closure.unbounded is not None:
            unbounded[test] = closure.unbounded
        if closure.files not in memo:
            memo[closure.files] = closure_digest(closure.files, state.digests)
        keys[test] = result_key(
            test=test,
            lane=settings.lane,
            args=settings.args,
            environment=settings.environment,
            tool=settings.tool,
            files_digest=memo[closure.files],
        )
        if keys[test] in passes:
            skippable.append(test)
    skipped = set(skippable)
    return TestPlan(
        keys=keys,
        skippable=tuple(skippable),
        run=tuple(test for test in sorted(tests) if test not in skipped),
        uncacheable=uncacheable,
        unbounded=unbounded,
    )
