"""Language-neutral records produced by a frontend's comment scanner."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from meizel.graph.model import Code, Problem
from meizel.graph.universe import Checkout
from meizel.language.json_containers import as_array, as_record
from meizel.language.json_scalars import as_int, as_text
from meizel.source_text import object_of

__all__ = [
    "CommentBlock",
    "CommentCache",
    "CommentLink",
    "CommentOptions",
    "CommentScan",
    "decode_comment_scan",
]


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


def decode_comment_scan(path: str, raw: object) -> CommentScan:
    entry = as_record(raw)
    blocks = tuple(
        CommentBlock(
            as_int(item["line"]),
            as_int(item["end_line"]),
            as_text(item["kind"]),
            as_text(item["text"]),
            as_text(item["raw_text"]),
        )
        for item in map(as_record, as_array(entry["blocks"]))
    )
    links = tuple(
        CommentLink(as_int(item["line"]), as_text(item["target"]))
        for item in map(as_record, as_array(entry["links"]))
    )
    problems = tuple(
        Problem(as_int(item["line"]), Code(as_text(item["code"])), as_text(item["message"]))
        for item in map(as_record, as_array(entry["problems"]))
    )
    return CommentScan(path, blocks, links, problems)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _encode(key: str, scan: CommentScan) -> str:
    record = asdict(scan)
    del record["path"]
    payload = json.dumps(record, separators=(",", ":"))
    return f"{_digest((key + '\n' + payload).encode())}\n{payload}"


def _decode(key: str, path: str, text: str) -> CommentScan | None:
    checksum, _, payload = text.partition("\n")
    if checksum != _digest((key + "\n" + payload).encode()):
        return None
    try:
        return decode_comment_scan(path, object_of(json.loads, payload))
    except (KeyError, TypeError, ValueError, RecursionError):
        return None


class CommentCache:
    def __init__(
        self,
        repo: Checkout,
        frontend: str,
        options: CommentOptions,
        sources: Mapping[str, bytes | str],
        *,
        runtime: str = "",
    ) -> None:
        self.repo = repo
        identity = repo.tree.scanner_identity()
        self.keys: dict[str, str] = {}
        if not identity:
            return
        context = json.dumps([identity, frontend, runtime, asdict(options)])
        prefix = f"comments:v1:{_digest(context.encode())}"
        # Each parser receives these exact bytes (or their lossless UTF-8 decoding). Git's blob
        # SHA can differ from what a checkout supplies through filters or line-ending conversion.
        self.keys = {
            path: f"{prefix}:{_digest(_source_bytes(source))}:{path}"
            for path, source in sources.items()
        }

    def load(self) -> dict[str, CommentScan]:
        scans: dict[str, CommentScan] = {}
        pending: dict[str, str] = {}
        for path, key in self.keys.items():
            memo = self.repo.memo_get(key)
            if isinstance(memo, CommentScan):
                scans[path] = memo
            else:
                pending[path] = key
        cached = self.repo.cache_get_many(list(pending.values()))
        for path, key in pending.items():
            if key in cached and (scan := _decode(key, path, cached[key])) is not None:
                self.repo.memo_put(key, scan)
                scans[path] = scan
        return scans

    def store(self, scans: Mapping[str, CommentScan]) -> None:
        updates: dict[str, str] = {}
        for path, scan in scans.items():
            if path not in self.keys:
                continue
            key = self.keys[path]
            self.repo.memo_put(key, scan)
            updates[key] = _encode(key, scan)
        self.repo.cache_put_many(updates)


def _source_bytes(source: bytes | str) -> bytes:
    return source.encode() if isinstance(source, str) else source
