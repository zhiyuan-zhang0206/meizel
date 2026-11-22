"""TypeScript and JavaScript comment and link scanner for the `[comments]` rule."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from meizel.graph.model import Code, MeizelError, Problem
from meizel.graph.universe import Universe
from meizel.language.comment_scan import CommentBlock, CommentLink, CommentOptions, CommentScan
from meizel.language.file_scan import read_source
from meizel.lint_common import run_node_analyzer
from meizel.source_text import is_mapping, is_object_list, object_of

__all__ = ["scan_typescript_comments", "typescript_comment_files"]

_COMMENT_EXTENSIONS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")


def typescript_comment_files(universe: Universe) -> tuple[str, ...]:
    return universe.files_ending(_COMMENT_EXTENSIONS)


def _decode_blocks(raw: object, path: str) -> tuple[CommentBlock, ...]:
    if not is_object_list(raw):
        raise ValueError(f"{path}: blocks must be a list")
    blocks: list[CommentBlock] = []
    for item in raw:
        if not is_mapping(item):
            raise ValueError(f"{path}: block entry must be an object")
        line = item.get("line")
        end_line = item.get("end_line")
        kind = item.get("kind")
        text = item.get("text")
        raw_text = item.get("raw_text")
        if (
            not isinstance(line, int)
            or isinstance(line, bool)
            or not isinstance(end_line, int)
            or isinstance(end_line, bool)
            or not isinstance(kind, str)
            or not isinstance(text, str)
            or not isinstance(raw_text, str)
        ):
            raise TypeError(f"{path}: malformed comment block entry")
        blocks.append(CommentBlock(line, end_line, kind, text, raw_text))
    return tuple(blocks)


def _decode_links(raw: object, path: str) -> tuple[CommentLink, ...]:
    if not is_object_list(raw):
        raise ValueError(f"{path}: links must be a list")
    links: list[CommentLink] = []
    for item in raw:
        if not is_mapping(item):
            raise ValueError(f"{path}: link entry must be an object")
        line = item.get("line")
        target = item.get("target")
        if not isinstance(line, int) or isinstance(line, bool) or not isinstance(target, str):
            raise TypeError(f"{path}: malformed comment link entry")
        links.append(CommentLink(line, target))
    return tuple(links)


def _decode_problems(raw: object, path: str) -> tuple[Problem, ...]:
    if not is_object_list(raw):
        raise ValueError(f"{path}: problems must be a list")
    problems: list[Problem] = []
    for item in raw:
        if not is_mapping(item):
            raise ValueError(f"{path}: problem entry must be an object")
        line = item.get("line")
        message = item.get("message")
        if not isinstance(line, int) or isinstance(line, bool) or not isinstance(message, str):
            raise TypeError(f"{path}: malformed problem entry")
        problems.append(Problem(line, Code.CODE_COMMENT, message))
    return tuple(problems)


def _decode_output(output: str, expected: Sequence[str]) -> dict[str, CommentScan]:
    payload = object_of(json.loads, output)
    if not is_mapping(payload):
        raise ValueError("TypeScript comment scan output must be a JSON object")
    files = payload.get("files")
    if not is_mapping(files):
        raise ValueError("missing files map in TypeScript comment scan output")
    results: dict[str, CommentScan] = {}
    for path in expected:
        entry: object = files.get(path)
        if not isinstance(entry, Mapping) or not is_mapping(entry):
            raise ValueError(f"TypeScript comment scanner omitted {path}")
        results[path] = CommentScan(
            path,
            _decode_blocks(entry.get("blocks"), path),
            _decode_links(entry.get("links"), path),
            _decode_problems(entry.get("problems"), path),
        )
    return results


def scan_typescript_comments(
    universe: Universe, paths: Sequence[str], options: CommentOptions
) -> dict[str, CommentScan]:
    if not paths:
        return {}
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
    if not contents:
        return results
    producer = Path(__file__).parent / "compiler" / "comments.mjs"
    request = {
        "sources": contents,
        "link_prefix": options.link_prefix,
        "inline_directives": list(options.inline_directives),
    }
    output = run_node_analyzer(
        universe.repo.tree,
        producer,
        json.dumps(request),
        frontend=universe.repo.tree.toolchain(),
    )
    try:
        results.update(_decode_output(output, list(contents)))
    except (TypeError, ValueError) as error:
        raise MeizelError(f"invalid TypeScript comment scan result: {error}") from error
    return results
