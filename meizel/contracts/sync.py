"""`sync --prune`: drop declared edges that no fact edge needs."""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard

from meizel.allowances import POLICY, Policy, parse, parse_snapshot
from meizel.contracts.analysis import Analysis, analyze
from meizel.contracts.debt_edit import prune as prune_debt
from meizel.contracts.declare import declare
from meizel.contracts.enumerations import write as write_role_regions
from meizel.contracts.manifest import manifest_path
from meizel.contracts.manifest_text import ENTRY, HEADER, entry_end, items, set_scope, unquote
from meizel.graph.model import MeizelError
from meizel.graph.universe import MANIFEST, Checkout, EditPlan
from meizel.language import SOURCE_EXTENSIONS

__all__ = [
    "prepare_policy_snapshot",
    "prune",
    "regenerate_role_regions",
    "remove_entries",
    "sync_manifests",
    "with_table",
]


def _rewrite_entry(lines: list[str], start: int, end: int, drop: set[str]) -> list[str]:
    match = ENTRY.match(lines[start])
    if match is None:
        raise MeizelError(f"line {start + 1}: not a manifest entry: {lines[start]!r}")
    block = "\n".join(lines[start : end + 1])
    kept = [item for item in items(block) if item not in drop]
    if not kept or "*" in drop:
        return []
    values = ", ".join(f'"{item}"' for item in kept)
    return [f"{match.group(1)}{match.group(2)} = [{values}]"]


_EXTERNAL_ENTRY = re.compile(r"""^\s*("[^"]*"|'[^']*'|[\w.-]+)\s*=\s*["']""")
_KEYED_ENTRY = re.compile(r"""^\s*("[^"]*"|'[^']*'|[\w.-]+)\s*=""")


# The `key = ...` line of a section whose entries each take one line.
def _keyed_line(section: str, line: str) -> re.Match[str] | None:
    if section in {"state", "roots", "purity"}:
        return _KEYED_ENTRY.match(line)
    return _EXTERNAL_ENTRY.match(line) if section in {"external", "dynamic-attrs"} else None


def remove_entries(text: str, removals: dict[str, dict[str, set[str]]]) -> str:
    """Remove `targets` from entries of `[uses]`/`[loads]`; comments elsewhere survive."""
    lines = text.splitlines()
    out: list[str] = []
    section = ""
    index = 0
    while index < len(lines):
        header = HEADER.match(lines[index])
        if header:
            section = header.group(1)
        reason = _keyed_line(section, lines[index])
        if reason and unquote(reason.group(1)) in removals.get(section, {}):
            index += 1
            continue
        entry = ENTRY.match(lines[index])
        if entry and section in removals:
            end = entry_end(lines, index)
            drop = removals[section].get(unquote(entry.group(2)))
            out.extend(_rewrite_entry(lines, index, end, drop) if drop else lines[index : end + 1])
            index = end + 1
            continue
        out.append(lines[index])
        index += 1
    return _drop_empty_sections(out)


# The policy text with `[header]` holding exactly `entries` (`path = reason`): the table is dropped
# wherever it stands and written again at the end, or left out when there is no entry.
def with_table(text: str, header: str, entries: Mapping[str, str]) -> str:
    kept: list[str] = []
    skipping = False
    for line in text.splitlines():
        if line.startswith("["):
            skipping = line.strip() == f"[{header}]"
        if not skipping:
            kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    if entries:
        kept.extend(
            [
                "",
                f"[{header}]",
                *(
                    f"{json.dumps(k, ensure_ascii=False)} = {json.dumps(v, ensure_ascii=False)}"
                    for k, v in sorted(entries.items())
                ),
            ]
        )
    return "\n".join(kept) + "\n" if kept else ""


def _drop_empty_sections(lines: list[str]) -> str:
    kept: list[str] = []
    for position, line in enumerate(lines):
        if HEADER.match(line):
            rest = lines[position + 1 :]
            following = next((x for x in rest if x.strip() and not x.strip().startswith("#")), "")
            if not following or HEADER.match(following):
                continue
        kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    return (
        "\n".join(kept) + "\n"
        if any(x.strip() and not x.strip().startswith("#") for x in kept)
        else ""
    )


Removals = dict[str, dict[str, dict[str, set[str]]]]


def _collect(analysis: Analysis) -> tuple[Removals, list[str]]:
    """What to remove from each manifest, and a line for each removal."""
    removals: Removals = {}
    changes: list[str] = []
    for directory, cf, ct in analysis.stale_edges:
        removals.setdefault(directory, {}).setdefault("uses", {}).setdefault(cf, set()).add(ct)
        changes.append(f"{manifest_path(directory)}: removed {cf} -> {ct}")
    for directory, name in analysis.stale_loads:
        removals.setdefault(directory, {}).setdefault("loads", {})[name] = {"*"}
        changes.append(f"{manifest_path(directory)}: removed [loads] {name}")
    for directory, child in analysis.stale_exports:
        removals.setdefault(directory, {}).setdefault("", {}).setdefault("exports", set()).add(
            child
        )
        changes.append(f"{manifest_path(directory)}: removed [exports] {child}")
    for directory, manifest in analysis.manifests.items():
        for section, key, target in manifest.dangling:
            table = removals.setdefault(directory, {}).setdefault(
                "" if section == "exports" else section, {}
            )
            table.setdefault(key or "exports", set()).add(target if target is not None else "*")
            arrow = " -> " if key and target else ""
            changes.append(
                f"{manifest_path(directory)}: removed [{section}] {key or ''}{arrow}{target or ''}"
                " (not a child any more)"
            )
    return removals, changes


def _plan_removals(root: Path, texts: Mapping[str, str], removals: Removals) -> EditPlan:
    writes: dict[Path, str] = {}
    deletes: list[Path] = []
    for relative, sections in removals.items():
        path = root / relative
        before = texts[relative]
        updated = remove_entries(before, sections)
        if updated == before:
            raise MeizelError(
                f"{path.relative_to(root)}: cannot remove {sections}; edit it by hand"
            )
        if updated:
            writes[path] = updated
        else:
            deletes.append(path)
    return EditPlan(writes=writes, deletes=tuple(deletes))


def _apply(repo: Checkout, removals: Removals) -> None:
    texts = {relative: repo.load_text(relative) for relative in removals}
    repo.apply_plan(_plan_removals(repo.root, texts, removals))


# Remove stale declarations until none remain; returns removal lines and final analysis.
def prune(repo: Checkout, jobs: int | None = None) -> tuple[list[str], Analysis]:
    changes: list[str] = []
    while True:
        # Each round reads the tree the previous round left, not the snapshot it started from.
        analysis = analyze(repo.universe(), jobs=jobs)
        removals, found = _collect(analysis)
        if not removals:
            return changes, analysis
        changes.extend(found)
        _apply(repo, {manifest_path(d): sections for d, sections in removals.items()})


def _refuse_untracked(repo: Checkout) -> None:
    untracked = repo.untracked_files(SOURCE_EXTENSIONS)
    if not untracked:
        return
    sample = ", ".join(untracked[:3])
    raise MeizelError(
        f"refusing to sync with {len(untracked)} untracked source/manifest file(s) "
        f"(e.g. {sample}) invisible to git-indexed analysis; "
        f"run 'git add -N {untracked[0]}' first so declarations for new files are not pruned"
    )


# What `meizel sync` reads from argv, checked once at the dispatch boundary: the handler below holds
# `bool`/`Sequence`/`int` instead of `argparse.Namespace` attributes, which are `Any`.
@dataclass(frozen=True)
class Sync:
    prune: bool
    declare: bool
    paths: Sequence[str]
    jobs: int | None


def sync_manifests(
    repo: Checkout, targets: list[str] | None, jobs: int | None, *, do_declare: bool
) -> tuple[list[str], list[str]]:
    _refuse_untracked(repo)
    pruned, analysis = prune(repo, jobs)
    lines = list(pruned)
    if not do_declare:
        return lines, []
    lowered = prune_debt(repo, jobs, analysis=analysis)
    lines.extend(lowered)
    declared, left = declare(repo, targets, jobs, analysis=None if lowered else analysis)
    lines.extend(declared)
    return lines, left


def _is_str_table(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(k, str) for k in value)


# Rewrite pre-v0.12 `[purity]` spellings (`"strict-to-be"` -> `"ratchet"`, `{ mode = "none", ... }`
# -> `{ mode = "off", ... }`) inside a disposable historical comparison snapshot only. Live `check`
# keeps zero aliases; malformed entries are left untouched so `_refuse_unreadable` still stops them.
def _normalize_purity_text(text: str, raw: object) -> str | None:
    if isinstance(raw, str):
        return set_scope(text, "purity", {".": "ratchet"}, {}) if raw == "strict-to-be" else None
    if not _is_str_table(raw):
        return None
    declarations: dict[str, str] = {}
    reasons: dict[str, str] = {}
    changed = False
    for key, value in raw.items():
        if isinstance(value, str) and value in {"strict", "ratchet"}:
            declarations[key] = value
            reasons[key] = ""
        elif value == "strict-to-be":
            declarations[key] = "ratchet"
            reasons[key] = ""
            changed = True
        elif (
            _is_str_table(value)
            and set(value) == {"mode", "why"}
            and isinstance(value["why"], str)
            and value["why"].strip()
            and value["mode"] in {"off", "none"}
        ):
            declarations[key] = "off"
            reasons[key] = value["why"].strip()
            changed = changed or value["mode"] == "none"
        else:
            return None
    return set_scope(text, "purity", declarations, reasons) if changed else None


def _normalize_purity_snapshots(repo: Checkout) -> None:
    writes: dict[Path, str] = {}
    for relative in sorted(repo.universe().files):
        if relative != MANIFEST and not relative.endswith(f"/{MANIFEST}"):
            continue
        text = repo.load_text(relative)
        try:
            document = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            continue
        if "purity" not in document:
            continue
        rewritten = _normalize_purity_text(text, document["purity"])
        if rewritten is not None:
            writes[repo.root / relative] = rewritten
    if writes:
        repo.apply_plan(EditPlan(writes=writes))


# The policy of a disposable comparison checkout, read once before anything is written there: a
# malformed or unknown table fails the comparison as unreadable instead of being judged.
def prepare_policy_snapshot(repo: Checkout) -> Policy:
    _normalize_purity_snapshots(repo)
    if not repo.has_file(POLICY):
        return Policy()
    text = repo.load_text(POLICY)
    policy, problems = parse_snapshot(text)
    if problems:
        raise MeizelError(f"cannot read the manifests of snapshot: {POLICY}: {problems[0]}")
    declared, _ = parse(text)
    missing = {
        rule: shapes for rule, shapes in policy.sections.items() if rule not in declared.sections
    }
    if missing:
        # A base from before `[sections]` is normalized in its disposable checkout: the shapes its
        # values were written in are declared there, so every later reader of that tree reads it as
        # the live format.
        lines = [
            line
            for rule, shapes in missing.items()
            for line in (
                f"[sections.{rule}]",
                *(f'"{section}" = "{shape}"' for section, shape in shapes.items()),
                "",
            )
        ]
        repo.apply_plan(EditPlan(writes={repo.root / POLICY: "\n".join(lines) + "\n" + text}))
    return policy


# The lists generated from the roles (`roles write`) belong to the device that wrote them: each replay
# regenerates them under the roles it judges by, as the checker would write them. A tree that declares
# no roles has no regions to write; one whose roles cannot be read is refused by the readability check
# that follows, which names the problem.
def regenerate_role_regions(checkout: Checkout) -> None:
    if not checkout.has_file(MANIFEST):
        return
    try:
        declared = checkout.tree.roles()
    except MeizelError:
        return
    write_role_regions(checkout, declared)
