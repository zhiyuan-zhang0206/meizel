from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

__all__ = ["SCHEMA", "CachePolicy", "closure_digest", "normalize_pytest_args", "result_key"]

# A change to what a key is made of, or to how a pass is stored, bumps this: every earlier entry
# stops matching instead of meaning something else.
SCHEMA = "v1"


# What the test cache reads from `[test-cache]` in `meizel.policy.toml`: the environment variables
# whose values are part of a key (a test that reads one declares it here), and the markers whose
# tests are never cached. `flaky` is always one of them.
@dataclass(frozen=True, slots=True)
class CachePolicy:
    env: tuple[str, ...] = ()
    uncacheable_markers: frozenset[str] = frozenset({"flaky"})

    @classmethod
    def from_policy_text(cls, policy_text: str | None) -> CachePolicy:
        try:
            document = tomllib.loads(policy_text or "")
        except tomllib.TOMLDecodeError:
            return cls()
        table = document.get("test-cache", {})
        if not isinstance(table, dict):
            return cls()

        def names(key: str) -> tuple[str, ...]:
            value = table.get(key, [])
            return (
                tuple(item for item in value if isinstance(item, str))
                if isinstance(value, list)
                else ()
            )

        return cls(
            env=tuple(sorted(names("env"))),
            uncacheable_markers=frozenset({"flaky", *names("uncacheable-markers")}),
        )


# Options that change nothing a test file computes: how the run is spread, reported or printed. Any
# option not named here is part of the key, so an unknown option keeps results apart instead of
# merging them. A value of one of the first two lists follows it as the next argument.
_NOISE_WITH_VALUE = frozenset(
    {
        "-n",
        "--numprocesses",
        "--dist",
        "--junit-xml",
        "--junitxml",
        "--count",
        "--files-from",
        "--durations",
        "--durations-min",
        "--tb",
        "--color",
    }
)
_TAKES_VALUE = frozenset(
    {
        "-m",
        "-k",
        "-p",
        "-c",
        "-W",
        "-o",
        "--ignore",
        "--ignore-glob",
        "--rootdir",
        "--deselect",
        "--confcutdir",
        "--import-mode",
        "--maxfail",
    }
)
_NOISE_FLAG = re.compile(r"-(?:q+|v+|r[a-zA-Z]+|n\d+)")


# The pytest arguments that decide what a test file does: the argument list without the test paths
# and without the options of `_NOISE_WITH_VALUE`, `-q`, `-v`, `-r...` and `-o junit_family=...`.
def normalize_pytest_args(args: Sequence[str]) -> tuple[str, ...]:
    kept: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        name = arg.split("=", 1)[0]
        value: str | None = None
        if "=" not in arg and name in _NOISE_WITH_VALUE | _TAKES_VALUE and index < len(args):
            value = args[index]
            index += 1
        if name in _NOISE_WITH_VALUE or _NOISE_FLAG.fullmatch(arg):
            continue
        if name == "-o" and (value or arg.partition("=")[2]).startswith("junit_family"):
            continue
        if not arg.startswith("-") and _is_test_path(arg):
            continue
        kept.append(arg)
        if value is not None:
            kept.append(value)
    return tuple(kept)


def _is_test_path(arg: str) -> bool:
    return "/" in arg or "::" in arg or arg.endswith(".py")


# One digest of a set of files: each path with its content digest, in path order.
def closure_digest(files: Iterable[str], digests: Mapping[str, str]) -> str:
    hasher = hashlib.sha256()
    for path in sorted(files):
        hasher.update(f"{path}\0{digests.get(path, 'absent')}\0".encode())
    return hasher.hexdigest()


# The key of one test file's result: the same key means the same result unless the test reads
# something no part of the key covers (the limits are in `meizel/docs/meizel.md`).
def result_key(
    *,
    test: str,
    lane: str,
    args: Sequence[str],
    environment: Mapping[str, str],
    tool: str,
    files_digest: str,
) -> str:
    material = json.dumps(
        {
            "schema": SCHEMA,
            "tool": tool,
            "test": test,
            "lane": lane,
            "args": list(normalize_pytest_args(args)),
            "environment": sorted(environment.items()),
            "files": files_digest,
        },
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()
