"""The TypeScript frontend's reading: which files it judges, and the compiler's records as `FileScan`s."""

from __future__ import annotations

from meizel import allowances
from meizel.allowances import Policy
from meizel.graph.model import MeizelError, Sources
from meizel.graph.universe import Universe
from meizel.language.file_scan import FileScan, read_source
from meizel.language.typescript.compiler import TsScan, load_ts_config, scan_batch

__all__ = [
    "scan_source",
    "scan_typescript",
    "scan_typescript_files",
    "typescript_extensions",
    "typescript_files",
    "typescript_scopes",
]


def typescript_files(universe: Universe, policy: Policy) -> tuple[str, ...]:
    config = load_ts_config(policy)
    active = (*config.scopes, *config.import_sources)
    return tuple(
        path
        for path in universe.typescript_files
        if path.endswith(config.extensions)
        and (not active or any(path == p or path.startswith(f"{p}/") for p in active))
    )


# The extensions the policy reads as TypeScript (`[typescript].extensions`).
def typescript_extensions(policy: Policy) -> tuple[str, ...]:
    return tuple(load_ts_config(policy).extensions)


# The directories whose TypeScript behavior this repository judges (`[typescript].scopes`): the
# caller needs the list, not the whole config.
def typescript_scopes(policy: Policy) -> tuple[str, ...]:
    return load_ts_config(policy).scopes


def scan_typescript(
    path: str, source: str, universe: Universe, policy: Policy | None = None
) -> TsScan:
    loaded = allowances.load(universe.repo) if policy is None else policy
    return scan_batch(universe, {path: source}, loaded, Sources())[path]


def _file_scan(ts: TsScan) -> FileScan:
    return FileScan(
        ts.path,
        facts=list(ts.facts),
        patches=list(ts.patches),
        problems=list(ts.problems),
        purity=list(ts.purity),
        ambient=list(ts.ambient),
        type_casts=list(ts.type_casts),
        any_collaborators=list(ts.any_collaborators),
        enum_subsets=list(ts.enum_subsets),
        symbols=ts.symbols,
        restricted=list(ts.restricted),
    )


def scan_source(
    universe: Universe, path: str, source: bytes, sources: Sources, *, policy: Policy
) -> FileScan:
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MeizelError(f"{path}: cannot decode TypeScript source as UTF-8: {error}") from error
    return _file_scan(scan_batch(universe, {path: text}, policy, sources)[path])


def scan_typescript_files(
    universe: Universe, paths: list[str], sources: Sources, policy: Policy
) -> dict[str, FileScan]:
    try:
        contents = {path: read_source(universe, path).decode("utf-8") for path in paths}
    except UnicodeDecodeError as error:
        raise MeizelError(f"cannot decode TypeScript source as UTF-8: {error}") from error
    scans = scan_batch(universe, contents, policy, sources)
    return {path: _file_scan(scan) for path, scan in scans.items()}
