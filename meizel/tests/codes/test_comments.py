"""Tests for the `[comments]` rule, Python/TS frontends, ratchet CLI, and debt-diff safety."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meizel.contracts.analysis import analyze
from meizel.entry import main
from meizel.graph.model import Code, Diagnostic
from meizel.tests.synthetic import RepoFactory, git, seat


def _run(root: Path, *args: str) -> int:
    return main(["--repo", str(root), "--jobs", "1", *args])


def _diags(root: Path, *, changed: list[str] | None = None) -> list[Diagnostic]:
    return analyze(seat(root), jobs=1, changed=changed).verdict


def _codes(root: Path, *, changed: list[str] | None = None) -> list[tuple[str, Code]]:
    return [(d.path, d.code) for d in _diags(root, changed=changed)]


def test_default_mode_off_skips_comment_checks(make_repo: RepoFactory) -> None:
    root = make_repo({"pkg/__init__.py": "", "pkg/a.py": "# free comment\nx = 1\n"})
    assert _codes(root) == []


@pytest.mark.parametrize(
    "policy_text",
    [
        '[comments]\nmode = "bogus"\n',
        '[comments]\nmode = "ratchet"\n',
        '[comments]\nmode = "strict"\ninline-directives = ["[unclosed"]\n',
    ],
    ids=["bad-mode", "ratchet-without-baseline", "bad-inline-regex"],
)
def test_policy_validation_rejects_bad_comments_config(
    make_repo: RepoFactory, policy_text: str
) -> None:
    root = make_repo({"meizel.policy.toml": policy_text, "pkg/__init__.py": ""})
    assert any(code is Code.POLICY_SYNTAX for _, code in _codes(root))


def test_python_exemptions_and_violations_in_strict_mode(make_repo: RepoFactory) -> None:
    root = make_repo(
        {
            "docs/spec.md": "# Spec\n",
            "meizel.policy.toml": (
                "[comments]\n"
                'mode = "strict"\n'
                'link-prefix = "doc:link"\n'
                'inline-directives = ["^# time-bomb-ok: \\\\S.*$"]\n'
                "allow-fixture-docstrings = true\n"
                'docstring-marker-symbols = ["__public_help__"]\n'
                'docstring-paths = ["sdk/**"]\n'
            ),
            "pkg/__init__.py": "",
            "pkg/ok.py": (
                "#!/usr/bin/env python3\n"
                "# doc:link docs/spec.md\n"
                "import pytest\n\n"
                "VALUE = 1  # noqa: S603 - fixed git query\n"
                "OTHER = 2  # pyright: ignore[reportPrivateUsage] - internal hook\n"
                "# time-bomb-ok: expires next release\n\n"
                "@pytest.fixture\n"
                "def sample():\n"
                '    """Fixture help text."""\n'
                "    return 1\n"
            ),
            "pkg/marked.py": (
                '"""Public module help."""\n'
                '__public_help__ = ["fn"]\n\n'
                "def fn() -> int:\n"
                '    """Public function help."""\n'
                "    return 1\n"
            ),
            "sdk/__init__.py": "",
            "sdk/api.py": ('"""SDK module help."""\nFLAG = True\n"""Attribute help."""\n'),
        }
    )
    assert _codes(root) == []


def test_python_test_path_never_exempts_marker_or_glob_docstrings(make_repo: RepoFactory) -> None:
    root = make_repo(
        {
            "meizel.policy.toml": (
                "[comments]\n"
                'mode = "strict"\n'
                'docstring-marker-symbols = ["__public_help__"]\n'
                'docstring-paths = ["tests/**"]\n'
            ),
            "tests/__init__.py": "",
            "tests/test_sample.py": (
                '"""Disallowed test docstring."""\n__public_help__ = ["x"]\nx = 1\n'
            ),
        }
    )
    assert _codes(root) == [("tests/test_sample.py", Code.CODE_COMMENT)]


def test_python_standalone_noqa_with_prose_and_unused_string_fail(make_repo: RepoFactory) -> None:
    root = make_repo(
        {
            "meizel.policy.toml": '[comments]\nmode = "strict"\n',
            "pkg/__init__.py": "",
            "pkg/bad.py": (
                "# noqa: S603 - smuggled prose on standalone line\n"
                '"unused literal"\n'
                "def f() -> int:\n"
                '    """Ordinary docstring."""\n'
                "    return 1\n"
            ),
        }
    )
    found = [d for d in _diags(root) if d.path == "pkg/bad.py"]
    assert len(found) == 3
    assert all(d.code is Code.CODE_COMMENT for d in found)


def test_broken_comment_link_is_hard_error_even_in_ratchet(make_repo: RepoFactory) -> None:
    root = make_repo(
        {
            "docs/ok.md": "# Ok\n",
            "meizel.policy.toml": (
                "[comments]\n"
                'mode = "ratchet"\n'
                'baseline = "meizel.comments_baseline.json"\n'
                'link-prefix = "doc:link"\n'
            ),
            "meizel.comments_baseline.json": '{"pkg/a.py": 1}\n',
            "pkg/__init__.py": "",
            "pkg/a.py": (
                "# doc:link docs/ok.md\n"
                "# doc:link docs/missing.md\n"
                "# doc:link ../outside.md\n"
                "# legacy comment\n"
                "x = 1\n"
            ),
        }
    )
    broken = [d for d in _diags(root) if d.code is Code.BROKEN_COMMENT_LINK]
    assert [(d.path, d.line) for d in broken] == [("pkg/a.py", 2), ("pkg/a.py", 3)]


def test_block_merging_ratchet_lifecycle_and_cli(
    make_repo: RepoFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(
        {
            "meizel.policy.toml": (
                '[comments]\nmode = "ratchet"\nbaseline = "meizel.comments_baseline.json"\n'
            ),
            "pkg/__init__.py": "",
            "pkg/a.py": (
                "# line 1 of block 1\n"
                "# line 2 of block 1\n"
                "# line 3 of block 1\n\n"
                "# block 2\n"
                "x = 1\n"
            ),
            "pkg/b.py": "# single block\ny = 2\n",
        }
    )
    # Missing baseline fails with comment-ratchet-stale.
    assert _codes(root) == [("meizel.comments_baseline.json", Code.COMMENT_RATCHET_STALE)]

    # `comments record` writes block counts (2 for a.py, 1 for b.py).
    assert _run(root, "comments", "record") == 0
    git(root, "add", "meizel.comments_baseline.json")
    baseline = json.loads((root / "meizel.comments_baseline.json").read_text())
    assert baseline == {"pkg/a.py": 2, "pkg/b.py": 1}
    assert _codes(root) == []

    # Shortening a multi-line block does not reduce block count.
    (root / "pkg/a.py").write_text("# line 1 of block 1\n\n# block 2\nx = 1\n")
    assert _codes(root) == []

    # Adding a new comment block fails immediately.
    (root / "pkg/a.py").write_text("# line 1\n\n# block 2\n\n# block 3\nx = 1\n")
    assert _codes(root) == [("pkg/a.py", Code.CODE_COMMENT)]

    # `comments prune` never raises a file's baseline.
    assert _run(root, "comments", "prune") == 0
    assert json.loads((root / "meizel.comments_baseline.json").read_text()) == {
        "pkg/a.py": 2,
        "pkg/b.py": 1,
    }
    assert _codes(root) == [("pkg/a.py", Code.CODE_COMMENT)]

    # Removing one block in a.py and deleting b.py triggers stale in both full and --changed.
    (root / "pkg/a.py").write_text("# block 2\nx = 1\n")
    git(root, "rm", "-f", "pkg/b.py")
    assert ("pkg/a.py", Code.COMMENT_RATCHET_STALE) in _codes(root, changed=["pkg/a.py"])
    assert ("meizel.comments_baseline.json", Code.COMMENT_RATCHET_STALE) in _codes(
        root, changed=["pkg/b.py"]
    )

    # `comments prune` tightens baseline to match.
    assert _run(root, "comments", "prune") == 0
    assert json.loads((root / "meizel.comments_baseline.json").read_text()) == {"pkg/a.py": 1}
    assert _codes(root) == []

    # `comments corpus` exports jsonl and markdown.
    capsys.readouterr()
    assert _run(root, "comments", "corpus", "--format", "jsonl", "--path", "pkg") == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["path"] == "pkg/a.py"
    assert rows[0]["kind"] == "comment"

    assert _run(root, "comments", "corpus", "--format", "markdown") == 0
    assert "## `pkg/a.py` (1 blocks)" in capsys.readouterr().out

    # Clearing all comments + prune triggers debt-paid prompting strict upgrade.
    (root / "pkg/a.py").write_text("x = 1\n")
    assert _run(root, "comments", "prune") == 0
    assert json.loads((root / "meizel.comments_baseline.json").read_text()) == {}
    assert _codes(root) == [("meizel.policy.toml", Code.DEBT_PAID)]


def test_typescript_and_javascript_comment_scanning(make_repo: RepoFactory) -> None:
    root = make_repo(
        {
            "docs/ui.md": "# UI\n",
            "meizel.policy.toml": (
                "[comments]\n"
                'mode = "strict"\n'
                'link-prefix = "doc:link"\n'
                'inline-directives = ["^// lint-ok: \\\\S.*$"]\n'
            ),
            "web/ok.ts": (
                "'use client';\n"
                "// doc:link docs/ui.md\n"
                "// lint-ok: generated bridge\n"
                "/** @deprecated */\n"
                "export function legacy(): number { return 1; }\n"
            ),
            "scripts/tool.mjs": (
                "#!/usr/bin/env node\n"
                "'use strict';\n"
                "// doc:link docs/missing.md\n"
                "// first line\n"
                "// second line\n"
                "/** JSDoc prose */\n"
                '"unused string";\n'
                "export const n = 1;\n"
            ),
        }
    )
    found = _diags(root)
    assert [d for d in found if d.path == "web/ok.ts"] == []
    tool_diags = [(d.line, d.code) for d in found if d.path == "scripts/tool.mjs"]
    assert tool_diags == [
        (3, Code.BROKEN_COMMENT_LINK),
        (4, Code.CODE_COMMENT),
        (6, Code.CODE_COMMENT),
        (7, Code.CODE_COMMENT),
    ]


def test_debt_diff_succeeds_when_introducing_comments_ratchet(
    make_repo: RepoFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(
        {
            "pkg/__init__.py": "",
            "pkg/a.py": "# pre-existing comment\nx = 1\n",
            "meizel.toml": "",
        }
    )
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "base")
    git(root, "branch", "-M", "main")
    (root / "meizel.policy.toml").write_text(
        '[comments]\nmode = "ratchet"\nbaseline = "meizel.comments_baseline.json"\n'
    )
    git(root, "add", "meizel.policy.toml")
    assert _run(root, "comments", "record") == 0
    git(root, "add", "meizel.comments_baseline.json")

    capsys.readouterr()
    assert _run(root, "debt", "diff", "--against", "main", "--on-growth", "fail") == 0
    assert _codes(root) == []
