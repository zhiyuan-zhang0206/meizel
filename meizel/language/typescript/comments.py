"""TypeScript and JavaScript comment and link scanner for the `[comments]` rule."""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from meizel.graph.model import Code, MeizelError, Problem
from meizel.graph.universe import Universe
from meizel.language.comment_scan import (
    CommentCache,
    CommentOptions,
    CommentScan,
    decode_comment_scan,
)
from meizel.language.file_scan import read_source
from meizel.lint_common import run_node_analyzer
from meizel.source_text import is_mapping, object_of

__all__ = ["scan_typescript_comments", "typescript_comment_files"]

_COMMENT_EXTENSIONS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")


def typescript_comment_files(universe: Universe) -> tuple[str, ...]:
    return universe.files_ending(_COMMENT_EXTENSIONS)


def _run(
    universe: Universe, contents: Mapping[str, str], options: CommentOptions
) -> tuple[str | None, dict[str, CommentScan]]:
    producer = Path(__file__).parent / "compiler" / "comments.mjs"
    request = {
        "sources": dict(contents),
        "link_prefix": options.link_prefix,
        "inline_directives": list(options.inline_directives),
    }
    tree = universe.repo.tree
    output = run_node_analyzer(tree, producer, json.dumps(request), frontend=tree.toolchain())
    try:
        return _decode_output(output, contents)
    except (KeyError, TypeError, ValueError) as error:
        raise MeizelError(f"invalid TypeScript comment scan result: {error}") from error


def _decode_output(
    output: str, expected: Collection[str]
) -> tuple[str | None, dict[str, CommentScan]]:
    payload = object_of(json.loads, output)
    if not is_mapping(payload):
        raise ValueError("output must be a JSON object")
    identity, files = payload["identity"], payload["files"]
    if identity is not None and not isinstance(identity, str):
        raise ValueError("invalid compiler fingerprint")
    if not is_mapping(files):
        raise ValueError("missing files map")
    return identity, {path: decode_comment_scan(path, files[path]) for path in expected}


def _scan_cached(
    universe: Universe, contents: Mapping[str, str], options: CommentOptions
) -> dict[str, CommentScan]:
    # Even a fully warm cache must resolve and load the locked compiler. The same producer
    # answers the probe and the parse so a replaced toolchain cannot stamp the wrong cache key.
    identity, _ = _run(universe, {}, options)
    if identity is None:
        return _run(universe, contents, options)[1]
    cache = CommentCache(universe.repo, "typescript", options, contents, runtime=identity)
    hits = cache.load()
    misses = {path: text for path, text in contents.items() if path not in hits}
    if not misses:
        return hits
    actual, fresh = _run(universe, misses, options)
    if actual != identity:
        return _run(universe, contents, options)[1] if hits else fresh
    cache.store(fresh)
    hits.update(fresh)
    return {path: hits[path] for path in contents}


def scan_typescript_comments(
    universe: Universe, paths: Sequence[str], options: CommentOptions, _jobs: int | None = None
) -> dict[str, CommentScan]:
    results: dict[str, CommentScan] = {}
    contents: dict[str, str] = {}
    for path in paths:
        raw = read_source(universe, path)
        try:
            contents[path] = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            results[path] = CommentScan(
                path, problems=(Problem(1, Code.CODE_COMMENT, f"cannot decode UTF-8: {error}"),)
            )
    if contents:
        results.update(_scan_cached(universe, contents, options))
    return results
