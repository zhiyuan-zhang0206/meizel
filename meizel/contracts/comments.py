"""The `[comments]` rule: link checks, block-level ratchet baseline, and CLI commands."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from meizel.allowances import POLICY, Policy
from meizel.contracts.policy import load_policy
from meizel.graph.model import Code, Diagnostic, MeizelError
from meizel.graph.universe import Checkout, EditPlan, Universe
from meizel.language import CommentOptions, CommentScan, enabled_frontends
from meizel.source_text import is_mapping, object_of

__all__ = [
    "CommentsCommand",
    "CommentsConfig",
    "check_comments",
    "run_comments",
]

_MODES = frozenset({"off", "ratchet", "strict"})


@dataclass(frozen=True, slots=True)
class CommentsConfig:
    mode: str
    baseline: str
    options: CommentOptions
    exclude_paths: tuple[str, ...]


@dataclass(frozen=True)
class CommentsCommand:
    comments_mode: str
    output_format: str
    path_prefix: str | None
    jobs: int | None = None


def _canonical_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and not path.is_absolute()
        and ".." not in path.parts
        and str(path) == value
        and "\\" not in value
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


def _read_config(policy: Policy) -> tuple[CommentsConfig, list[Diagnostic]]:
    mode_vals = policy.names("comments", "mode")
    mode = mode_vals[0] if mode_vals else "off"
    baseline_vals = policy.names("comments", "baseline")
    baseline = baseline_vals[0] if baseline_vals else ""
    link_vals = policy.names("comments", "link-prefix")
    link_prefix = link_vals[0] if link_vals else ""
    inline_directives = policy.names("comments", "inline-directives")
    fixture_vals = policy.names("comments", "allow-fixture-docstrings")
    allow_fixtures = fixture_vals == ("true",)
    marker_symbols = policy.names("comments", "docstring-marker-symbols")
    docstring_paths = policy.names("comments", "docstring-paths")
    exclude_paths = policy.names("comments", "exclude-paths")

    config = CommentsConfig(
        mode=mode,
        baseline=baseline,
        options=CommentOptions(
            link_prefix=link_prefix,
            inline_directives=inline_directives,
            allow_fixture_docstrings=allow_fixtures,
            docstring_marker_symbols=marker_symbols,
            docstring_paths=docstring_paths,
        ),
        exclude_paths=exclude_paths,
    )
    if mode not in _MODES:
        return config, [
            Diagnostic(
                POLICY,
                policy.line_of("mode", "comments"),
                Code.POLICY_SYNTAX,
                f"[comments] mode must be off, ratchet or strict, not {mode!r}",
            )
        ]
    if mode == "off":
        return config, []

    problems: list[Diagnostic] = []
    if mode == "ratchet" and not baseline:
        problems.append(
            Diagnostic(
                POLICY,
                policy.line_of("mode", "comments"),
                Code.POLICY_SYNTAX,
                '[comments] baseline is required when mode = "ratchet"',
                ('set baseline = "meizel.comments_baseline.json" under [comments]',),
            )
        )
    if baseline and not _canonical_path(baseline):
        problems.append(
            Diagnostic(
                POLICY,
                policy.line_of("baseline", "comments"),
                Code.POLICY_SYNTAX,
                f"[comments] baseline {baseline!r} must be a canonical repository-relative path",
            )
        )
    if link_prefix and any(ch.isspace() for ch in link_prefix):
        problems.append(
            Diagnostic(
                POLICY,
                policy.line_of("link-prefix", "comments"),
                Code.POLICY_SYNTAX,
                f"[comments] link-prefix {link_prefix!r} must not contain whitespace",
            )
        )
    for pattern in inline_directives:
        try:
            re.compile(pattern)
        except re.error as error:
            problems.append(
                Diagnostic(
                    POLICY,
                    policy.line_of(pattern, "comments"),
                    Code.POLICY_SYNTAX,
                    f"[comments] inline-directives pattern {pattern!r} is invalid regex: {error}",
                )
            )
    return config, problems


def _scan_files(
    universe: Universe,
    policy: Policy,
    config: CommentsConfig,
    changed: Collection[str] | None = None,
    *,
    jobs: int | None = None,
) -> tuple[dict[str, CommentScan], frozenset[str]]:
    excludes = tuple(_glob_to_regex(pattern) for pattern in config.exclude_paths)
    all_files: list[str] = []
    scans: dict[str, CommentScan] = {}
    for frontend in enabled_frontends(policy):
        candidates = [
            path
            for path in frontend.comment_files(universe)
            if not any(pattern.fullmatch(path) for pattern in excludes)
        ]
        all_files.extend(candidates)
        selected = (
            candidates if changed is None else [path for path in candidates if path in changed]
        )
        if selected:
            scans.update(frontend.scan_comments(universe, selected, config.options, jobs))
    return scans, frozenset(all_files)


def _read_baseline(
    universe: Universe, baseline_path: str
) -> tuple[dict[str, int] | None, list[Diagnostic]]:
    if baseline_path not in universe.files:
        return None, []
    try:
        raw = object_of(json.loads, universe.repo.load_text(baseline_path))
    except (OSError, ValueError) as error:
        return None, [
            Diagnostic(
                baseline_path,
                1,
                Code.POLICY_SYNTAX,
                f"invalid comment baseline JSON: {error}",
            )
        ]
    if not is_mapping(raw):
        return None, [
            Diagnostic(
                baseline_path,
                1,
                Code.POLICY_SYNTAX,
                "comment baseline must be a JSON object mapping paths to positive integers",
            )
        ]
    counts: dict[str, int] = {}
    for path, value in raw.items():
        if not _canonical_path(path):
            return None, [
                Diagnostic(
                    baseline_path,
                    1,
                    Code.POLICY_SYNTAX,
                    f"comment baseline key {path!r} is not a canonical relative path",
                )
            ]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            return None, [
                Diagnostic(
                    baseline_path,
                    1,
                    Code.POLICY_SYNTAX,
                    f"comment baseline entry {path!r} must be a positive integer, not {value!r}",
                )
            ]
        counts[path] = value
    return counts, []


def _format_spans(scan: CommentScan) -> str:
    return ", ".join(
        f"{block.line}-{block.end_line}" if block.end_line > block.line else str(block.line)
        for block in scan.blocks
    )


def _link_and_parse_diagnostics(
    universe: Universe, scans: Mapping[str, CommentScan], link_prefix: str
) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    for path in sorted(scans):
        scan = scans[path]
        for problem in scan.problems:
            found.append(Diagnostic(path, problem.line, problem.code, problem.message))
        for link in scan.links:
            if not _canonical_path(link.target) or link.target not in universe.files:
                found.append(
                    Diagnostic(
                        path,
                        link.line,
                        Code.BROKEN_COMMENT_LINK,
                        f"{link_prefix} target {link.target!r} is not a tracked regular file",
                        ("point the link to an existing tracked file, or remove the link",),
                    )
                )
    return found


def _strict_diagnostics(
    universe: Universe, config: CommentsConfig, scans: Mapping[str, CommentScan]
) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    for path in sorted(scans):
        for block in scans[path].blocks:
            span = (
                f"lines {block.line}-{block.end_line}"
                if block.end_line > block.line
                else f"line {block.line}"
            )
            found.append(
                Diagnostic(
                    path,
                    block.line,
                    Code.CODE_COMMENT,
                    f"disallowed {block.kind} ({span})",
                    ("remove the comment or replace it with a documentation link",),
                )
            )
    if config.baseline and config.baseline in universe.files:
        baseline, problems = _read_baseline(universe, config.baseline)
        found.extend(problems)
        if baseline is not None:
            found.append(
                Diagnostic(
                    config.baseline,
                    1,
                    Code.COMMENT_RATCHET_STALE,
                    f'{config.baseline} is no longer needed when [comments] mode = "strict"',
                    (f"delete {config.baseline} and remove [comments] baseline",),
                )
            )
    return found


def _ratchet_diagnostics(
    universe: Universe,
    policy: Policy,
    config: CommentsConfig,
    scans: Mapping[str, CommentScan],
    all_files: frozenset[str],
    changed: Collection[str] | None,
) -> list[Diagnostic]:
    baseline, problems = _read_baseline(universe, config.baseline)
    if problems:
        return problems
    if baseline is None:
        return [
            Diagnostic(
                config.baseline,
                1,
                Code.COMMENT_RATCHET_STALE,
                f"comment baseline {config.baseline!r} does not exist",
                (f"run `python -m meizel comments record` to create {config.baseline}",),
            )
        ]

    found: list[Diagnostic] = []
    for path in sorted(scans):
        scan = scans[path]
        actual = len(scan.blocks)
        expected = baseline.get(path, 0)
        if actual > expected:
            found.append(
                Diagnostic(
                    path,
                    scan.blocks[0].line,
                    Code.CODE_COMMENT,
                    f"{actual} comment block(s), baseline allows {expected} "
                    f"(blocks at lines {_format_spans(scan)})",
                    ("remove the added comment block(s), or link to documentation instead",),
                )
            )
        elif actual < expected:
            found.append(
                Diagnostic(
                    path,
                    1,
                    Code.COMMENT_RATCHET_STALE,
                    f"{path} has {actual} comment block(s), baseline records {expected}",
                    ("run `python -m meizel comments prune` to tighten the baseline",),
                )
            )

    if changed is None:
        for path, expected in sorted(baseline.items()):
            if path not in all_files:
                found.append(
                    Diagnostic(
                        config.baseline,
                        1,
                        Code.COMMENT_RATCHET_STALE,
                        f"{path} is recorded in {config.baseline} ({expected}) but no longer exists",
                        ("run `python -m meizel comments prune` to tighten the baseline",),
                    )
                )
        if not baseline and all(not scan.blocks for scan in scans.values()):
            found.append(
                Diagnostic(
                    POLICY,
                    policy.line_of("mode", "comments"),
                    Code.DEBT_PAID,
                    f"[comments] {config.baseline} is empty and 0 comment blocks remain",
                    ('upgrade [comments] mode = "strict" and delete the baseline file',),
                )
            )
    else:
        for path in sorted(changed):
            if path in baseline and path not in all_files:
                found.append(
                    Diagnostic(
                        config.baseline,
                        1,
                        Code.COMMENT_RATCHET_STALE,
                        f"{path} is recorded in {config.baseline} ({baseline[path]}) "
                        "but no longer exists",
                        ("run `python -m meizel comments prune` to tighten the baseline",),
                    )
                )
    return found


def check_comments(
    universe: Universe,
    policy: Policy,
    *,
    changed: Collection[str] | None = None,
    jobs: int | None = None,
) -> list[Diagnostic]:
    config, problems = _read_config(policy)
    if config.mode == "off" or problems:
        return problems
    scans, all_files = _scan_files(universe, policy, config, changed, jobs=jobs)
    found = _link_and_parse_diagnostics(universe, scans, config.options.link_prefix)
    if config.mode == "strict":
        found.extend(_strict_diagnostics(universe, config, scans))
    else:
        found.extend(_ratchet_diagnostics(universe, policy, config, scans, all_files, changed))
    return found


def _render_baseline(counts: Mapping[str, int]) -> str:
    return json.dumps(dict(sorted(counts.items())), indent=2) + "\n"


def _require_baseline_config(universe: Universe) -> tuple[Policy, CommentsConfig]:
    policy, policy_problems = load_policy(universe)
    if policy_problems:
        raise MeizelError(policy_problems[0].render())
    config, config_problems = _read_config(policy)
    if config_problems:
        raise MeizelError(config_problems[0].render())
    if not config.baseline:
        raise MeizelError("[comments] baseline must be configured in meizel.policy.toml")
    return policy, config


def _run_record(repo: Checkout, jobs: int | None) -> int:
    universe = repo.universe()
    policy, config = _require_baseline_config(universe)
    scans, _ = _scan_files(universe, policy, config, jobs=jobs)
    counts = {path: len(scan.blocks) for path, scan in sorted(scans.items()) if scan.blocks}
    total_blocks = sum(counts.values())
    total_links = sum(len(scan.links) for scan in scans.values())
    repo.apply_plan(EditPlan(writes={repo.root / config.baseline: _render_baseline(counts)}))
    print(
        f"meizel: recorded {total_blocks} comment block(s) across {len(counts)} file(s) "
        f"({len(scans)} files scanned, {total_links} links) into {config.baseline}"
    )
    return 0


def _run_prune(repo: Checkout, jobs: int | None) -> int:
    universe = repo.universe()
    policy, config = _require_baseline_config(universe)
    baseline, problems = _read_baseline(universe, config.baseline)
    if problems:
        raise MeizelError(problems[0].render())
    if baseline is None:
        raise MeizelError(f"{config.baseline}: baseline file does not exist")
    scans, _ = _scan_files(universe, policy, config, jobs=jobs)
    updated: dict[str, int] = {}
    for path, old in sorted(baseline.items()):
        if path not in scans:
            continue
        actual = len(scans[path].blocks)
        kept = min(old, actual)
        if kept >= 1:
            updated[path] = kept
    before_total = sum(baseline.values())
    after_total = sum(updated.values())
    repo.apply_plan(EditPlan(writes={repo.root / config.baseline: _render_baseline(updated)}))
    print(
        f"meizel: pruned {config.baseline} from {before_total} to {after_total} comment block(s) "
        f"({len(baseline)} -> {len(updated)} files)"
    )
    return 0


def _matches_prefix(path: str, prefix: str | None) -> bool:
    if not prefix:
        return True
    cleaned = prefix.rstrip("/")
    return path == cleaned or path.startswith(f"{cleaned}/")


def _run_corpus(
    repo: Checkout, output_format: str, path_prefix: str | None, jobs: int | None
) -> int:
    universe = repo.universe()
    policy, policy_problems = load_policy(universe)
    if policy_problems:
        raise MeizelError(policy_problems[0].render())
    config, config_problems = _read_config(policy)
    if config_problems:
        raise MeizelError(config_problems[0].render())
    scans, _ = _scan_files(universe, policy, config, jobs=jobs)
    selected = {
        path: scan
        for path, scan in sorted(scans.items())
        if scan.blocks and _matches_prefix(path, path_prefix)
    }
    if output_format == "jsonl":
        for path, scan in selected.items():
            for block in scan.blocks:
                row = {
                    "path": path,
                    "line": block.line,
                    "end_line": block.end_line,
                    "kind": block.kind,
                    "lines": block.end_line - block.line + 1,
                    "chars": len(block.text),
                    "text": block.text,
                    "raw_text": block.raw_text,
                }
                print(json.dumps(row, ensure_ascii=False))
        return 0

    by_kind: Counter[str] = Counter()
    total_lines = 0
    for scan in selected.values():
        for block in scan.blocks:
            by_kind[block.kind] += 1
            total_lines += block.end_line - block.line + 1
    total_blocks = sum(by_kind.values())
    kind_summary = ", ".join(f"{kind}: {count}" for kind, count in sorted(by_kind.items()))
    print(
        f"# Comment Corpus ({total_blocks} blocks across {len(selected)} files, {total_lines} lines)"
    )
    if kind_summary:
        print(f"- By kind: {kind_summary}")
    for path, scan in selected.items():
        print(f"\n## `{path}` ({len(scan.blocks)} blocks)")
        for block in scan.blocks:
            span = (
                f"L{block.line}-L{block.end_line}"
                if block.end_line > block.line
                else f"L{block.line}"
            )
            print(f"- **{span}** (`{block.kind}`, {len(block.text)} chars):")
            for line in block.raw_text.splitlines():
                print(f"  > {line}")
    return 0


def run_comments(repo: Checkout, opts: CommentsCommand) -> int:
    if opts.comments_mode == "record":
        return _run_record(repo, opts.jobs)
    if opts.comments_mode == "prune":
        return _run_prune(repo, opts.jobs)
    return _run_corpus(repo, opts.output_format, opts.path_prefix, opts.jobs)
