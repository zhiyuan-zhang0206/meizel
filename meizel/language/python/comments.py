"""Python comment and link scanner for the `[comments]` rule."""

from __future__ import annotations

import ast
import inspect
import io
import re
import tokenize
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from itertools import pairwise

from meizel.graph.model import Code, Problem
from meizel.graph.universe import Universe
from meizel.language.comment_scan import (
    CommentBlock,
    CommentCache,
    CommentLink,
    CommentOptions,
    CommentScan,
)
from meizel.language.file_scan import read_source
from meizel.language.python.comment_fixtures import fixture_owners
from meizel.language.test_files import is_test_file

__all__ = ["scan_python_comments"]

_PARALLEL_FROM = 200
_SHEBANG = re.compile(r"#!/usr/bin/(?:env python(?:3(?:\.12)?)?|python3(?:\.12)?)")
_RUFF_CODE = r"[A-Z]+[0-9]{3,4}"
_PYRIGHT_CODE = r"report[A-Z][A-Za-z0-9]+"
_LINT_BARE = re.compile(
    rf"# noqa: {_RUFF_CODE}(?:, ?{_RUFF_CODE})*"
    rf"|# pyright: ignore\[{_PYRIGHT_CODE}(?:, ?{_PYRIGHT_CODE})*\]"
)
_LINT_INLINE = re.compile(
    rf"(?:# noqa: {_RUFF_CODE}(?:, ?{_RUFF_CODE})*"
    rf"|# pyright: ignore\[{_PYRIGHT_CODE}(?:, ?{_PYRIGHT_CODE})*\])(?:[ \t]+.*)?"
)


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    parts: list[str] = ["^"]
    index = 0
    length = len(pattern)
    while index < length:
        if pattern[index : index + 3] == "**/":
            parts.append("(?:.*/)?")
            index += 3
        elif pattern[index : index + 2] == "**":
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    parts.append("$")
    return re.compile("".join(parts))


def _declares_marker(tree: ast.Module, markers: frozenset[str]) -> bool:
    if not markers:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in markers:
            return True
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id in markers for t in node.targets):
                return True
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in markers
        ):
            return True
    return False


def _is_test_module(path: str) -> bool:
    return "/tests/" in path or path.startswith("tests/") or is_test_file(path)


def _assignment_name(node: ast.stmt) -> str | None:
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ):
        return node.targets[0].id
    return None


def _attribute_docs(body: list[ast.stmt]) -> list[tuple[ast.Expr, str]]:
    result: list[tuple[ast.Expr, str]] = []
    for previous, node in pairwise(body):
        if (
            _assignment_name(previous)
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            result.append((node, node.value.value))
    return result


def _collect_string_blocks(
    tree: ast.Module,
    text: str,
    fixtures: frozenset[str],
    *,
    exempt_docstrings: bool,
) -> list[CommentBlock]:
    blocks: list[CommentBlock] = []
    doc_nodes: set[int] = set()

    def walk_body(
        node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
        scope: list[str],
    ) -> None:
        owner = ".".join(scope) or "<module>"
        value = ast.get_docstring(node, clean=True)
        if value is not None:
            first = node.body[0]
            doc_nodes.add(id(first))
            if not exempt_docstrings and owner not in fixtures:
                blocks.append(
                    CommentBlock(
                        first.lineno,
                        first.end_lineno or first.lineno,
                        "docstring",
                        value,
                        ast.get_source_segment(text, first) or "",
                    )
                )
        for expression, raw_doc in _attribute_docs(node.body):
            doc_nodes.add(id(expression))
            if not exempt_docstrings:
                blocks.append(
                    CommentBlock(
                        expression.lineno,
                        expression.end_lineno or expression.lineno,
                        "docstring",
                        inspect.cleandoc(raw_doc),
                        ast.get_source_segment(text, expression) or "",
                    )
                )
        for child in node.body:
            walk_stmt(child, scope)

    def walk_stmt(node: ast.stmt, scope: list[str]) -> None:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            walk_body(node, [*scope, node.name])
            return
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and id(node) not in doc_nodes
        ):
            blocks.append(
                CommentBlock(
                    node.lineno,
                    node.end_lineno or node.lineno,
                    "unused-string",
                    node.value.value,
                    ast.get_source_segment(text, node) or "",
                )
            )
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                walk_stmt(child, scope)

    walk_body(tree, [])
    return blocks


def _strip_hash(raw: str) -> str:
    body = raw[1:]
    return body[1:] if body.startswith(" ") else body


def _merge_hash_comments(comments: list[tuple[int, int, str]]) -> list[CommentBlock]:
    blocks: list[CommentBlock] = []
    index = 0
    while index < len(comments):
        start_line, col, first_raw = comments[index]
        end_line = start_line
        bodies = [_strip_hash(first_raw)]
        raws = [first_raw]
        cursor = index + 1
        while cursor < len(comments):
            next_line, next_col, next_raw = comments[cursor]
            if next_col != col or next_line != end_line + 1:
                break
            bodies.append(_strip_hash(next_raw))
            raws.append(next_raw)
            end_line = next_line
            cursor += 1
        blocks.append(
            CommentBlock(
                start_line,
                end_line,
                "comment",
                "\n".join(bodies).strip("\n"),
                "\n".join(raws),
            )
        )
        index = cursor
    return blocks


def _scan_one(
    path: str,
    text: str,
    options: CommentOptions,
    *,
    link_pattern: re.Pattern[str] | None,
    directives: tuple[re.Pattern[str], ...],
    doc_globs: tuple[re.Pattern[str], ...],
) -> CommentScan:
    try:
        tree = ast.parse(text, filename=path)
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (SyntaxError, tokenize.TokenError) as error:
        lineno = getattr(error, "lineno", None) or 1
        return CommentScan(path, problems=(Problem(lineno, Code.CODE_COMMENT, str(error)),))

    lines = text.splitlines()
    exempt_docstrings = not _is_test_module(path) and (
        any(pattern.fullmatch(path) for pattern in doc_globs)
        or _declares_marker(tree, frozenset(options.docstring_marker_symbols))
    )
    fixtures = fixture_owners(tree) if options.allow_fixture_docstrings else frozenset()

    blocks = _collect_string_blocks(tree, text, fixtures, exempt_docstrings=exempt_docstrings)
    links: list[CommentLink] = []
    raw_comments: list[tuple[int, int, str]] = []

    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        line, col = token.start
        raw = token.string
        if (line, col) == (1, 0) and _SHEBANG.fullmatch(raw):
            continue
        if link_pattern is not None:
            matched = link_pattern.fullmatch(raw)
            if matched is not None:
                links.append(CommentLink(line, matched.group(1)))
                continue
        standalone = not lines[line - 1][:col].strip()
        if (standalone and _LINT_BARE.fullmatch(raw)) or (
            not standalone and _LINT_INLINE.fullmatch(raw)
        ):
            continue
        stripped = raw.strip()
        if any(pattern.fullmatch(stripped) for pattern in directives):
            continue
        raw_comments.append((line, col, raw))

    blocks.extend(_merge_hash_comments(raw_comments))
    blocks.sort(key=lambda item: (item.line, item.end_line, item.kind))
    return CommentScan(path, tuple(blocks), tuple(links))


def _scan_source(
    path: str,
    raw: bytes,
    *,
    options: CommentOptions,
    link_pattern: re.Pattern[str] | None,
    directives: tuple[re.Pattern[str], ...],
    doc_globs: tuple[re.Pattern[str], ...],
) -> CommentScan:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        return CommentScan(
            path, problems=(Problem(1, Code.CODE_COMMENT, f"cannot decode UTF-8: {error}"),)
        )
    return _scan_one(
        path,
        text,
        options,
        link_pattern=link_pattern,
        directives=directives,
        doc_globs=doc_globs,
    )


def _scan_misses(
    sources: Mapping[str, bytes], options: CommentOptions, jobs: int | None
) -> dict[str, CommentScan]:
    if not sources:
        return {}
    task = partial(
        _scan_source,
        options=options,
        link_pattern=(
            re.compile(rf"#\s*{re.escape(options.link_prefix)}\s+(\S+)\s*")
            if options.link_prefix
            else None
        ),
        directives=tuple(re.compile(pattern) for pattern in options.inline_directives),
        doc_globs=tuple(_glob_to_regex(pattern) for pattern in options.docstring_paths),
    )
    if jobs is None or jobs <= 1 or len(sources) < _PARALLEL_FROM:
        return {path: task(path, raw) for path, raw in sources.items()}
    with ProcessPoolExecutor(jobs) as pool:
        chunk = max(1, len(sources) // (jobs * 8))
        return {
            scan.path: scan for scan in pool.map(task, sources, sources.values(), chunksize=chunk)
        }


def scan_python_comments(
    universe: Universe, paths: Sequence[str], options: CommentOptions, jobs: int | None = None
) -> dict[str, CommentScan]:
    sources = {path: read_source(universe, path) for path in paths}
    cache = CommentCache(universe.repo, "python", options, sources)
    hits = cache.load()
    fresh = _scan_misses(
        {path: raw for path, raw in sources.items() if path not in hits}, options, jobs
    )
    cache.store(fresh)
    hits.update(fresh)
    return {path: hits[path] for path in sources}
