"""Language-neutral records produced by a frontend's comment scanner."""

from __future__ import annotations

from dataclasses import dataclass

from meizel.graph.model import Problem

__all__ = ["CommentBlock", "CommentLink", "CommentOptions", "CommentScan"]


@dataclass(frozen=True, slots=True)
class CommentOptions:
    link_prefix: str = ""
    inline_directives: tuple[str, ...] = ()
    allow_fixture_docstrings: bool = False
    docstring_marker_symbols: tuple[str, ...] = ()
    docstring_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CommentBlock:
    line: int
    end_line: int
    kind: str
    text: str
    raw_text: str


@dataclass(frozen=True, slots=True)
class CommentLink:
    line: int
    target: str


@dataclass(frozen=True, slots=True)
class CommentScan:
    path: str
    blocks: tuple[CommentBlock, ...] = ()
    links: tuple[CommentLink, ...] = ()
    problems: tuple[Problem, ...] = ()
