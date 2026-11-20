# Content-addressed JSON serialization and SQLite-backed caching for `FileScan` and `Sources`.
# See meizel/docs/checker/checker.md.

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Collection, Mapping
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

from meizel.allowances import POLICY, Policy
from meizel.graph.model import (
    Sources,
)
from meizel.graph.universe import Universe
from meizel.language.file_scan import FileScan
from meizel.language.python.record import decode_record, encode_record, python_record
from meizel.language.python.resolve import PythonModules, python_modules
from meizel.language.python.scanner import scan_file
from meizel.language.scan_codec import (
    decode_file_scan,
    decode_imports,
    decode_sources,
    encode_file_scan,
    encode_imports,
    encode_sources,
)
from meizel.source_text import object_of, object_pairs

__all__ = [
    "cached_module_imports",
    "load_cached_sources",
    "scan_python_cached",
    "store_cached_sources",
]

_PARALLEL_FROM = 200
_MISSING = "<missing>"
_WORKER: dict[str, tuple[Universe, Sources, Policy]] = {}


@dataclass(frozen=True, slots=True)
class _CachedPyScan:
    scan: FileScan
    deps: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _CachedImports:
    imports: dict[str, str]


def _policy_digest(policy: Policy) -> str:
    payload = {
        "external": sorted(policy.external.items()),
        "dynamic-attrs": sorted(policy.dynamic_attrs.items()),
        "loads": [[k, list(v)] for k, v in sorted(policy.loads.items())],
        "defaults": list(policy.default_arguments),
        "listed": [[r, s, sorted(v.items())] for (r, s), v in sorted(policy.listed.items())],
        "named": [[r, s, list(v)] for (r, s), v in sorted(policy.named.items())],
        "unless": [[r, s, sorted(v.items())] for (r, s), v in sorted(policy.unless.items())],
    }
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _projects_digest(universe: PythonModules) -> str:
    payload = [
        [item.directory, [[name, target] for name, target in item.packages]]
        for item in universe.standalone_projects
    ]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def load_cached_sources(
    universe: PythonModules, state_digest: str, policy: Policy
) -> tuple[str, Sources | None]:
    digests = universe.file_digests()
    if not digests or any(path not in digests for path in universe.python_files):
        return "", None
    repo = universe.repo
    hasher = hashlib.sha256()
    hasher.update(
        f"{repo.scanner_digest()}\0{state_digest}\0{_policy_digest(policy)}\0{_projects_digest(universe)}\0".encode()
    )
    for path in universe.python_files:
        hasher.update(f"{path}:{digests[path]}\0".encode())
    key = f"sources:v1:{hasher.hexdigest()}"
    memo = repo.memo_get(key)
    if isinstance(memo, Sources):
        return key, memo
    hit = repo.cache_get_many((key,)).get(key)
    if hit is None:
        return key, None
    try:
        decoded = decode_sources(hit)
    except (ValueError, TypeError, KeyError, IndexError):
        return key, None
    repo.memo_put(key, decoded)
    return key, decoded


def store_cached_sources(universe: PythonModules, cache_key: str, sources: Sources) -> None:
    if cache_key:
        universe.repo.memo_put(cache_key, sources)
        universe.repo.cache_put_many({cache_key: encode_sources(sources)})


def _partition_memo_imports(
    universe: PythonModules, keys: Mapping[str, str]
) -> tuple[dict[str, dict[str, str]], list[str]]:
    found: dict[str, dict[str, str]] = {}
    pending: list[str] = []
    for path, key in keys.items():
        memo = universe.repo.memo_get(key)
        if isinstance(memo, _CachedImports):
            found[path] = dict(memo.imports)
        else:
            pending.append(path)
    return found, pending


def cached_module_imports(
    universe: PythonModules,
    paths: Collection[str],
    compute: Callable[[PythonModules, str], dict[str, str]],
) -> dict[str, dict[str, str]]:
    ordered = sorted(paths)
    if not ordered:
        return {}
    digests = universe.file_digests()
    if not digests or any(path not in digests for path in ordered):
        return {path: compute(universe, path) for path in ordered}
    repo = universe.repo
    prefix = f"pyimp:v1:{repo.scanner_digest()}:{_projects_digest(universe)}"
    keys = {path: f"{prefix}:{path}:{digests[path]}" for path in ordered}
    found, pending = _partition_memo_imports(universe, keys)
    if not pending:
        return found
    cached = repo.cache_get_many([keys[p] for p in pending])
    updates: dict[str, str] = {}
    for path in pending:
        key = keys[path]
        hit = cached.get(key)
        decoded = None if hit is None else decode_imports(hit)
        if decoded is None:
            decoded = compute(universe, path)
            updates[key] = encode_imports(decoded)
        repo.memo_put(key, _CachedImports(decoded))
        found[path] = decoded
    if updates:
        repo.cache_put_many(updates)
    return found


def _py_context_digest(
    universe: PythonModules, sources: Sources, policy: Policy, digests: Mapping[str, str]
) -> str:
    hasher = hashlib.sha256()
    repo = universe.repo
    policy_present = POLICY in universe.files
    policy_blob = digests.get(POLICY, _MISSING) if policy_present else _MISSING
    hasher.update(
        (
            f"{repo.scanner_digest()}\0{_policy_digest(policy)}\0"
            f"{policy_present}:{policy_blob}\0{encode_sources(sources)}\0"
            f"{_projects_digest(universe)}\0"
        ).encode()
    )
    for path in universe.python_files:
        hasher.update(f"p:{path}\0".encode())
    for directory in sorted(universe.dirs):
        hasher.update(f"d:{directory}\0".encode())
    for root_name in sorted(universe.roots):
        hasher.update(f"r:{root_name}\0".encode())
    return hasher.hexdigest()


def _deps_valid(deps: tuple[tuple[str, str], ...], digests: Mapping[str, str]) -> bool:
    return all(digests.get(dep, _MISSING) == expected for dep, expected in deps)


def _decode_py_entry(
    text: str, digests: Mapping[str, str], kinds: Collection[str]
) -> _CachedPyScan | None:
    # The first line holds the dependencies the record was made under and the rest is the record.
    head, _, body = text.partition("\n")
    try:
        deps = tuple(
            (str(dep), str(expected)) for dep, expected in object_pairs(object_of(json.loads, head))
        )
        if not _deps_valid(deps, digests):
            return None
        return _CachedPyScan(decode_file_scan(body, kinds, decode_record), deps)
    except (ValueError, TypeError, KeyError, IndexError):
        return None


def _encode_py_entry(scan: FileScan, text: str, digests: Mapping[str, str]) -> str:
    deps = [[dep, digests.get(dep, _MISSING)] for dep in python_record(scan).deps]
    return f"{json.dumps(deps, separators=(',', ':'))}\n{text}"


def _init_worker(universe: Universe, sources: Sources, policy: Policy) -> None:
    _WORKER["scan"] = (universe, sources, policy)


def _scan_in_worker(path: str) -> tuple[FileScan, str]:
    universe, sources, policy = _WORKER["scan"]
    scan = scan_file(universe, path, sources, policy=policy)
    return scan, encode_file_scan(scan, encode_record)


def _scan_python_misses(
    universe: PythonModules, sources: Sources, paths: list[str], jobs: int | None, policy: Policy
) -> list[tuple[FileScan, str]]:
    workers = 1 if jobs is None else jobs
    if workers <= 1 or len(paths) < _PARALLEL_FROM:
        return [
            (scan, encode_file_scan(scan, encode_record))
            for scan in (scan_file(universe.universe, p, sources, policy=policy) for p in paths)
        ]
    with ProcessPoolExecutor(
        workers, initializer=_init_worker, initargs=(universe.universe, sources, policy)
    ) as pool:
        chunk = max(1, len(paths) // (workers * 8))
        return list(pool.map(_scan_in_worker, paths, chunksize=chunk))


def _from_py_memo(
    universe: PythonModules,
    paths: list[str],
    keys: Mapping[str, str],
    digests: Mapping[str, str],
) -> tuple[dict[str, FileScan], list[str]]:
    scans: dict[str, FileScan] = {}
    pending: list[str] = []
    for path in paths:
        memo = universe.repo.memo_get(keys[path]) if path in keys else None
        if isinstance(memo, _CachedPyScan) and _deps_valid(memo.deps, digests):
            scans[path] = memo.scan
        else:
            pending.append(path)
    return scans, pending


def _partition_py_cache(
    universe: PythonModules,
    paths: list[str],
    ctx: str,
    digests: Mapping[str, str],
    kinds: Collection[str],
) -> tuple[dict[str, str], dict[str, FileScan], list[str]]:
    keys = {p: f"pyscan:v1:{ctx}:{p}:{digests[p]}" for p in paths if p in digests}
    scans, pending = _from_py_memo(universe, paths, keys, digests)
    db_keys = [keys[p] for p in pending if p in keys]
    cached = universe.repo.cache_get_many(db_keys) if db_keys else {}
    misses: list[str] = []
    for path in pending:
        hit = cached.get(keys[path]) if path in keys else None
        decoded = None if hit is None else _decode_py_entry(hit, digests, kinds)
        if decoded is not None and path in keys:
            universe.repo.memo_put(keys[path], decoded)
            scans[path] = decoded.scan
        else:
            misses.append(path)
    return keys, scans, misses


def _store_py_scans(
    universe: PythonModules,
    fresh: list[tuple[FileScan, str]],
    keys: Mapping[str, str],
    digests: Mapping[str, str],
) -> None:
    updates: dict[str, str] = {}
    for scan, text in fresh:
        if scan.path not in keys or any(dep not in digests for dep in python_record(scan).deps):
            continue
        key = keys[scan.path]
        deps = tuple((dep, digests[dep]) for dep in python_record(scan).deps)
        universe.repo.memo_put(key, _CachedPyScan(scan, deps))
        updates[key] = _encode_py_entry(scan, text, digests)
    if updates:
        universe.repo.cache_put_many(updates)


def scan_python_cached(
    base: Universe,
    paths: list[str],
    sources: Sources,
    jobs: int | None,
    policy: Policy,
) -> dict[str, FileScan]:
    if not paths:
        return {}
    universe = python_modules(base)
    digests = universe.file_digests()
    if not digests:
        return {
            scan.path: scan
            for scan, _ in _scan_python_misses(universe, sources, paths, jobs, policy)
        }
    ctx = _py_context_digest(universe, sources, policy, digests)
    keys, scans, misses = _partition_py_cache(universe, paths, ctx, digests, policy.reader_kinds)
    if not misses:
        return scans
    fresh = _scan_python_misses(universe, sources, misses, jobs, policy)
    for scan, _ in fresh:
        scans[scan.path] = scan
    _store_py_scans(universe, fresh, keys, digests)
    return scans
