from __future__ import annotations

import json
from datetime import date

from meizel.test_graph.cache_key import SCHEMA

__all__ = ["PASS_PREFIX", "decode_pass", "encode_pass", "is_fresh", "pass_key"]

# The prefix of a recorded pass among the entries of the scan cache's file.
PASS_PREFIX = f"test-pass:{SCHEMA}:"


def pass_key(key: str) -> str:
    return f"{PASS_PREFIX}{key}"


def encode_pass(day: str, run: str) -> str:
    return json.dumps({"day": day, "run": run}, separators=(",", ":"))


def decode_pass(value: str) -> dict[str, object] | None:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


# Whether a recorded pass is young enough to be reused: a pass older than `ttl_days` is a miss, so
# every test file runs again at least that often even when nothing it reads is known to have changed.
def is_fresh(value: str, today: str, ttl_days: int) -> bool:
    record = decode_pass(value)
    day = record.get("day") if record is not None else None
    if not isinstance(day, str):
        return False
    try:
        return (date.fromisoformat(today) - date.fromisoformat(day)).days <= ttl_days
    except ValueError:
        return False
