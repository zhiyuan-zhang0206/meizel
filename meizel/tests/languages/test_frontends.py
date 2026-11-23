# The language frontends: a repository chooses its languages under `[languages] enabled`, and only
# the files of those languages are read. The refusal and the dispatch need no Node; the default
# run reads TypeScript and so needs the locked compiler, which the static lane installs.
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from meizel import allowances
from meizel.graph.model import MeizelError, Sources
from meizel.language import FRONTENDS, enabled_frontends, scan_all
from meizel.tests.synthetic import RepoFactory, seat

CLOCK_PY = "import time\n\ndef stamp() -> float:\n    return time.time()\n"
CLOCK_TS = "export const stamp = (): number => Date.now();\n"


def _policy(languages: str) -> allowances.Policy:
    policy, problems = allowances.parse(languages)
    assert not problems
    return policy


def test_every_frontend_runs_when_the_policy_names_none() -> None:
    assert [f.name for f in enabled_frontends(allowances.Policy())] == ["python", "typescript"]


def test_the_policy_names_the_frontends_in_order_and_once() -> None:
    policy = _policy('[languages]\nenabled = ["typescript", "python", "typescript"]\n')
    assert [f.name for f in enabled_frontends(policy)] == ["typescript", "python"]


def test_an_unknown_frontend_is_refused_and_the_known_ones_are_named() -> None:
    policy = _policy('[languages]\nenabled = ["python", "cobol"]\n')
    with pytest.raises(MeizelError, match=r"names cobol; the frontends are python, typescript"):
        enabled_frontends(policy)


def test_each_frontend_owns_only_the_files_of_its_language() -> None:
    policy = allowances.Policy()
    python, typescript = FRONTENDS["python"], FRONTENDS["typescript"]
    assert python.owns("pkg/a.py", policy) and not python.owns("pkg/a.ts", policy)
    for path in ("pkg/a.ts", "pkg/a.tsx", "pkg/a.mts", "pkg/a.cts"):
        assert typescript.owns(path, policy) and not python.owns(path, policy)
    assert not typescript.owns("pkg/a.py", policy)
    assert not typescript.owns("pkg/a.rs", policy)


# `meizel check` in a process whose PATH holds git and nothing else, so the TypeScript compiler
# cannot start; the process environment is the child's own and nothing here patches this one's.
def _check_without_node(root: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = shutil.which("git")
    assert git is not None
    (bin_dir / "git").symlink_to(git)
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "meizel.tests.languages.check_probe", "--repo", str(root), "check"],
        env={"PATH": str(bin_dir)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_policy_that_enables_only_python_needs_no_node(
    make_repo: RepoFactory, tmp_path: Path
) -> None:
    root = make_repo(
        {
            "pkg/meizel.toml": "",
            "pkg/stamp.py": CLOCK_PY,
            "pkg/stamp.ts": CLOCK_TS,
            "meizel.policy.toml": '[languages]\nenabled = ["python"]\n',
        }
    )
    universe = seat(root)
    policy = allowances.load(universe.repo)
    assert sorted(scan_all(universe, Sources(), policy=policy)) == ["pkg/stamp.py"]
    assert scan_all(universe, Sources(), paths=["pkg/stamp.ts"], policy=policy) == {}
    result = _check_without_node(root, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "0 TypeScript files" in result.stdout


def test_the_same_repository_without_the_policy_does_need_node(
    make_repo: RepoFactory, tmp_path: Path
) -> None:
    root = make_repo({"pkg/meizel.toml": "", "pkg/stamp.ts": CLOCK_TS})
    result = _check_without_node(root, tmp_path)
    assert result.returncode != 0
    assert "TypeScript compiler unavailable" in result.stdout + result.stderr


def test_the_default_run_reads_both_languages(make_repo: RepoFactory) -> None:
    root = make_repo({"pkg/meizel.toml": "", "pkg/stamp.py": CLOCK_PY, "pkg/stamp.ts": CLOCK_TS})
    universe = seat(root)
    scans = scan_all(universe, Sources(), policy=allowances.load(universe.repo))
    assert sorted(scans) == ["pkg/stamp.py", "pkg/stamp.ts"]


def test_a_policy_that_enables_only_typescript_leaves_python_unread(
    make_repo: RepoFactory,
) -> None:
    root = make_repo(
        {
            "pkg/meizel.toml": "",
            "pkg/stamp.py": CLOCK_PY,
            "pkg/stamp.ts": CLOCK_TS,
            "meizel.policy.toml": '[languages]\nenabled = ["typescript"]\n',
        }
    )
    universe = seat(root)
    scans = scan_all(universe, Sources(), policy=allowances.load(universe.repo))
    assert sorted(scans) == ["pkg/stamp.ts"]


@pytest.mark.parametrize("first_mode", ["default", "error"])
def test_comment_cache_preserves_warning_policy_and_prune(
    make_repo: RepoFactory, first_mode: str
) -> None:
    root = make_repo(
        {
            "a.py": '# retained comment\nvalue = "\\q"\n',
            "meizel.policy.toml": '[comments]\nmode = "ratchet"\nbaseline = "baseline.json"\n',
            "baseline.json": '{"a.py": 1}\n',
        }
    )

    def run(mode: str, *args: str) -> subprocess.CompletedProcess[bytes]:
        # Fixed CLI argv, with the warning policy scoped to this process.
        return subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "meizel.tests.languages.check_probe",
                "--jobs",
                "1",
                "comments",
                *args,
            ],
            cwd=root,
            capture_output=True,
            check=True,
            env={**os.environ, "PYTHONWARNINGS": f"{mode}::SyntaxWarning"},
        )

    def expect_corpus(mode: str) -> tuple[bytes, bytes]:
        result = run(mode, "corpus", "--format", "jsonl")
        if mode == "default":
            assert b"retained comment" in result.stdout
            assert b"SyntaxWarning: invalid escape sequence" in result.stderr
        else:
            assert result.stdout == result.stderr == b""
        return result.stdout, result.stderr

    other_mode = "error" if first_mode == "default" else "default"
    first = expect_corpus(first_mode)
    second = expect_corpus(other_mode)
    assert expect_corpus(first_mode) == first
    assert expect_corpus(other_mode) == second
    prune = run("default", "prune")
    assert b"SyntaxWarning: invalid escape sequence" in prune.stderr
    assert json.loads((root / "baseline.json").read_text()) == {"a.py": 1}
