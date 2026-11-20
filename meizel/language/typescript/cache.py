# The TypeScript frontend's scan cache: one batch of records per key, in the JSON `scan_codec` writes.

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from meizel.allowances import Policy
from meizel.graph.model import Sources
from meizel.graph.universe import MANIFEST, Universe
from meizel.language.file_scan import FileScan
from meizel.language.scan_codec import decode_file_scan, encode_file_scan
from meizel.language.typescript.adapter import scan_typescript_files
from meizel.language.typescript.compiler import load_ts_config

__all__ = ["scan_typescript_cached"]

_TS_WORLD_SUFFIXES = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".json")


@dataclass(frozen=True, slots=True)
class _CachedTsBatch:
    scans: dict[str, FileScan]


def _ts_batch_key(
    universe: Universe,
    paths: list[str],
    sources: Sources,
    policy: Policy,
    digests: Mapping[str, str],
) -> str:
    if not digests or any(path not in digests for path in paths):
        return ""
    non_manifest = [p for p in sorted(universe.files) if p.rsplit("/", 1)[-1] != MANIFEST]
    world_files = [p for p in non_manifest if p.endswith(_TS_WORLD_SUFFIXES)]
    if any(p not in digests for p in world_files):
        return ""
    cfg = load_ts_config(policy)
    payload = {
        "scanner": universe.repo.scanner_digest(),
        "paths": paths,
        "config": {
            "scopes": list(cfg.scopes),
            "import_sources": list(cfg.import_sources),
            "aliases": [[a, b] for a, b in cfg.aliases],
            "extensions": list(cfg.extensions),
            "impure_calls": sorted(cfg.impure_calls),
            "impure_hooks": sorted(cfg.impure_hooks),
            "max_public_symbols": cfg.max_public_symbols,
            "max_params": cfg.max_params,
            "max_attr_hops": cfg.max_attr_hops,
            "inlined_env_prefix": cfg.inlined_env_prefix,
            "inlined_env_roots": list(cfg.inlined_env_roots),
        },
        "ambient": {
            "names": sorted((k, str(v)) for k, v in sources.names.items()),
            "calls": sorted((k, str(v)) for k, v in sources.calls.items()),
        },
        "world": [[p, digests[p]] for p in world_files],
    }
    digest = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()
    return f"tsbatch:v1:{digest}"


def scan_typescript_cached(
    universe: Universe, paths: list[str], sources: Sources, policy: Policy
) -> dict[str, FileScan]:
    if not paths:
        return {}
    digests = universe.file_digests()
    key = _ts_batch_key(universe, paths, sources, policy, digests)
    if not key:
        return scan_typescript_files(universe, paths, sources, policy)
    repo = universe.repo
    memo = repo.memo_get(key)
    if isinstance(memo, _CachedTsBatch) and set(memo.scans) == set(paths):
        return dict(memo.scans)
    hit = repo.cache_get_many((key,)).get(key)
    if hit is not None:
        try:
            decoded = {
                s.path: s
                for s in (decode_file_scan(line, policy.reader_kinds) for line in hit.split("\n"))
            }
            if set(decoded) == set(paths):
                repo.memo_put(key, _CachedTsBatch(decoded))
                return decoded
        except (ValueError, TypeError, KeyError, IndexError):
            decoded = {}
    scans = scan_typescript_files(universe, paths, sources, policy)
    repo.memo_put(key, _CachedTsBatch(dict(scans)))
    encoded = "\n".join(encode_file_scan(scans[p]) for p in paths)
    repo.cache_put_many({key: encoded})
    return scans
