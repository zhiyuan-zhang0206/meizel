from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from meizel.graph.model import MeizelError
from meizel.source_text import is_mapping, is_object_list
from meizel.test_graph import (
    PASS_PREFIX,
    CachePolicy,
    InputClosure,
    PlanSettings,
    TestPlan,
    decode_pass,
    encode_pass,
    input_closures,
    is_fresh,
    outcomes_from_junit,
    pass_key,
    plan_tests,
    recordable_tests,
    shadow_report,
)
from meizel.test_graph.model import TestGraphState, TestLanes

__all__ = [
    "CacheDeps",
    "CacheExport",
    "CacheImport",
    "CachePlan",
    "CachePrune",
    "CacheRecord",
    "CacheReport",
    "CacheRepository",
    "run_cache_command",
]


# What the test cache asks of the repository handle: the digested test graph, the lanes, and the
# entries the scan cache's file holds. `GitRepo` is the one implementation.
class CacheRepository(Protocol):
    def load_text(self, rel: str, *, default: str | None = None) -> str: ...
    def test_graph_state(self) -> TestGraphState: ...
    def test_lanes(self) -> TestLanes: ...
    def scanner_digest(self) -> str: ...
    def cache_get_many(self, keys: Collection[str]) -> dict[str, str]: ...
    def cache_put_many(self, entries: Mapping[str, str]) -> None: ...
    def cache_items(self, prefix: str) -> dict[str, str]: ...
    def cache_delete_many(self, keys: Collection[str]) -> None: ...


# What only the process entry can read, handed down: where the paths of an argv are read from, the
# day, and the environment a key is made of (the interpreter, the platform and the declared
# variables).
@dataclass(frozen=True, slots=True)
class CacheDeps:
    base: Path
    read_file: Callable[[Path, str], str]
    today: str
    environment: Callable[[Sequence[str]], dict[str, str]]


@dataclass(frozen=True)
class CachePlan:
    lane: str
    tests_file: str | None
    closures_file: str | None
    pytest_arg: Sequence[str]
    env: Sequence[str]
    ttl_days: int


@dataclass(frozen=True)
class CacheRecord:
    plan: str
    junit: Sequence[str]
    run: str


@dataclass(frozen=True)
class CacheReport:
    plan: str
    junit: Sequence[str]
    durations: str | None
    strict: bool


@dataclass(frozen=True)
class CacheExport:
    ttl_days: int


@dataclass(frozen=True)
class CacheImport:
    file: str
    ttl_days: int


@dataclass(frozen=True)
class CachePrune:
    ttl_days: int


def _lines(deps: CacheDeps, path: str) -> list[str]:
    try:
        text = deps.read_file(deps.base, path)
    except OSError as error:
        raise MeizelError(f"{path}: cannot read: {error}") from error
    return [line.strip() for line in text.splitlines() if line.strip()]


def _json(deps: CacheDeps, path: str) -> object:
    try:
        return json.loads(deps.read_file(deps.base, path))
    except (OSError, json.JSONDecodeError) as error:
        raise MeizelError(f"{path}: cannot read as JSON: {error}") from error


# Closures a host computed itself, as `{test: {"files": [...], "unbounded": reason-or-null}}`: the
# host's selection knows more than the graph here does, and the cache must not be bolder than it. A
# test with a reason is keyed by every file of the tree, so the host lists no files for it.
def _host_closures(deps: CacheDeps, path: str, tree: frozenset[str]) -> dict[str, InputClosure]:
    document = _json(deps, path)
    if not is_mapping(document):
        raise MeizelError(f"{path}: closures must be a JSON object")
    closures: dict[str, InputClosure] = {}
    for test, entry in document.items():
        files = entry.get("files") if is_mapping(entry) else None
        reason = entry.get("unbounded") if is_mapping(entry) else None
        if isinstance(reason, str):
            closures[test] = InputClosure(tree, reason)
        elif is_object_list(files):
            closures[test] = InputClosure(frozenset(i for i in files if isinstance(i, str)))
        else:
            raise MeizelError(f"{path}: {test}: expected {{files: [...]}} or {{unbounded: reason}}")
    return closures


def _environment(deps: CacheDeps, policy: CachePolicy, extra: Sequence[str]) -> dict[str, str]:
    environment = deps.environment(policy.env)
    for item in extra:
        name, sep, value = item.partition("=")
        if not sep or not name:
            raise MeizelError(f"--env {item}: expected NAME=VALUE")
        environment[f"extra:{name}"] = value
    return environment


def _plan(repo: CacheRepository, deps: CacheDeps, opts: CachePlan) -> int:
    state = repo.test_graph_state()
    lanes = repo.test_lanes()
    in_lane = lanes.static if opts.lane == "static" else lanes.native
    tests = (
        {line for line in _lines(deps, opts.tests_file) if line in state.checkout.collectable}
        if opts.tests_file is not None
        else set(in_lane)
    )
    closures = (
        _host_closures(deps, opts.closures_file, state.checkout.all_files)
        if opts.closures_file is not None
        else input_closures(state.checkout, state.facts)
    )
    policy = CachePolicy.from_policy_text(repo.load_text("meizel.policy.toml", default=""))
    candidate = {
        key: value
        for key, value in repo.cache_items(PASS_PREFIX).items()
        if is_fresh(value, deps.today, opts.ttl_days)
    }
    settings = PlanSettings(
        lane=opts.lane,
        args=opts.pytest_arg,
        environment=_environment(deps, policy, opts.env),
        tool=repo.scanner_digest(),
        policy=policy,
    )
    plan = plan_tests(
        tests,
        state,
        lanes,
        closures,
        settings,
        {key.removeprefix(PASS_PREFIX) for key in candidate},
    )
    print(plan.as_json())
    return 0


def _read_plan(deps: CacheDeps, path: str) -> TestPlan:
    document = _json(deps, path)
    if not is_mapping(document):
        raise MeizelError(f"{path}: a plan is a JSON object")
    keys = document.get("keys")
    if not is_mapping(keys):
        raise MeizelError(f"{path}: the plan has no keys")
    skippable = document.get("skippable")
    run = document.get("run")
    uncacheable = document.get("uncacheable")
    unbounded = document.get("unbounded")
    return TestPlan(
        keys={str(k): str(v) for k, v in keys.items()},
        skippable=tuple(str(t) for t in skippable) if is_object_list(skippable) else (),
        run=tuple(str(t) for t in run) if is_object_list(run) else (),
        uncacheable={str(k): str(v) for k, v in uncacheable.items()}
        if is_mapping(uncacheable)
        else {},
        unbounded={str(k): str(v) for k, v in unbounded.items()} if is_mapping(unbounded) else {},
    )


def _outcomes(deps: CacheDeps, plan: TestPlan, junit: Sequence[str]) -> dict[str, str]:
    known = set(plan.keys) | set(plan.uncacheable)
    return outcomes_from_junit((deps.read_file(deps.base, path) for path in junit), known)


def _record(repo: CacheRepository, deps: CacheDeps, opts: CacheRecord) -> int:
    plan = _read_plan(deps, opts.plan)
    recorded = recordable_tests(plan, _outcomes(deps, plan, opts.junit))
    repo.cache_put_many(
        {pass_key(plan.keys[test]): encode_pass(deps.today, opts.run) for test in recorded}
    )
    print(json.dumps({"recorded": len(recorded), "tests": list(recorded)}, sort_keys=True))
    return 0


def _read_durations(deps: CacheDeps, path: str | None) -> dict[str, float]:
    if path is None:
        return {}
    document = _json(deps, path)
    if not is_mapping(document):
        raise MeizelError(f"{path}: durations are a JSON object of seconds by test file")
    return {str(k): float(v) for k, v in document.items() if isinstance(v, (int, float))}


def _report(deps: CacheDeps, opts: CacheReport) -> int:
    plan = _read_plan(deps, opts.plan)
    report = shadow_report(
        plan, _outcomes(deps, plan, opts.junit), _read_durations(deps, opts.durations)
    )
    print(report.as_json())
    return 1 if opts.strict and report.would_skip_failed else 0


def _export(repo: CacheRepository, deps: CacheDeps, opts: CacheExport) -> int:
    for key, value in sorted(repo.cache_items(PASS_PREFIX).items()):
        if is_fresh(value, deps.today, opts.ttl_days):
            print(json.dumps({"k": key.removeprefix(PASS_PREFIX), "v": value}, sort_keys=True))
    return 0


def _import(repo: CacheRepository, deps: CacheDeps, opts: CacheImport) -> int:
    entries: dict[str, str] = {}
    for line in _lines(deps, opts.file):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = item.get("k") if is_mapping(item) else None
        value = item.get("v") if is_mapping(item) else None
        if (
            isinstance(key, str)
            and isinstance(value, str)
            and decode_pass(value) is not None
            and is_fresh(value, deps.today, opts.ttl_days)
        ):
            entries[pass_key(key)] = value
    repo.cache_put_many(entries)
    print(json.dumps({"imported": len(entries)}, sort_keys=True))
    return 0


def _prune(repo: CacheRepository, deps: CacheDeps, opts: CachePrune) -> int:
    stale = [
        key
        for key, value in repo.cache_items(PASS_PREFIX).items()
        if not is_fresh(value, deps.today, opts.ttl_days)
    ]
    repo.cache_delete_many(stale)
    print(json.dumps({"pruned": len(stale)}, sort_keys=True))
    return 0


# The command a parsed `test-cache` argv names, over the shapes the dispatcher read.
def run_cache_command(
    repo: CacheRepository,
    deps: CacheDeps,
    mode: str,
    shape: CachePlan | CacheRecord | CacheReport | CacheExport | CacheImport | CachePrune,
) -> int:
    if isinstance(shape, CachePlan) and mode == "plan":
        return _plan(repo, deps, shape)
    if isinstance(shape, CacheRecord) and mode == "record":
        return _record(repo, deps, shape)
    if isinstance(shape, CacheReport) and mode == "report":
        return _report(deps, shape)
    if isinstance(shape, CacheExport) and mode == "export":
        return _export(repo, deps, shape)
    if isinstance(shape, CacheImport) and mode == "import":
        return _import(repo, deps, shape)
    if isinstance(shape, CachePrune) and mode == "prune":
        return _prune(repo, deps, shape)
    raise MeizelError(f"test-cache {mode}: unknown mode")
