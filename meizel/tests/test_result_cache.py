"""The test result cache: what a key is made of, what is never cached, and the commands around it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meizel.entry import main, open_repository
from meizel.tests.synthetic import RepoFactory, commit, git

PYPROJECT = '[tool.pytest.ini_options]\ntestpaths = ["tests", "pkg/**/tests"]\n'
ROLES = '[roles]\napplication = ["pkg"]\ntests = ["tests"]\n'
POLICY = (
    "[test-graph]\n"
    'native-fixtures = ["db_url"]\n'
    'global-files = ["settings.cfg"]\n'
    'frontend-prefixes = ["ui/"]\n'
    'doc-dirs = ["docs"]\n'
    "[test-cache]\n"
    'uncacheable-markers = ["network"]\n'
)
SOURCES = {
    "pyproject.toml": PYPROJECT,
    "meizel.policy.toml": POLICY,
    "meizel.toml": ROLES,
    "uv.lock": "# lock\n",
    "settings.cfg": "x = 1\n",
    "ui/app.tsx": "export {}\n",
    "docs/guide.md": "# guide\n",
    "README.md": "# readme\n",
    "pkg/__init__.py": "",
    "pkg/calc.py": "def double(x: int) -> int:\n    return x * 2\n",
    "pkg/other.py": "VALUE = 1\n",
    "scripts/tool.py": "VALUE = 1\n",
    "pkg/data/table.csv": "a,b\n",
    "pkg/tests/__init__.py": "",
    "pkg/tests/conftest.py": "import pytest\n",
    "pkg/tests/test_calc.py": (
        "from pkg.calc import double\ndef test_double() -> None:\n    assert double(3) == 6\n"
    ),
    "pkg/tests/test_resource.py": (
        "from pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parents[1]\n"
        "def test_table() -> None:\n    assert (ROOT / 'data' / 'table.csv').read_text()\n"
    ),
    "tests/test_scratch.py": (
        "def test_scratch(tmp_path) -> None:\n"
        "    (tmp_path / 'a.txt').write_text('x')\n"
        "    assert (tmp_path / 'a.txt').read_text()\n"
    ),
    "tests/test_repo_read.py": (
        "from pathlib import Path\n"
        "def test_reads() -> None:\n    assert Path('README.md').read_text()\n"
    ),
    "tests/test_db.py": "def test_db(db_url: str) -> None:\n    assert db_url\n",
    "tests/test_slow.py": (
        "import pytest\n@pytest.mark.network\ndef test_slow() -> None:\n    pass\n"
    ),
}


def cached(root: Path, capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, object]:
    assert main(["--repo", str(root), "--jobs", "1", "test-cache", *args]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    return json.loads(out[-1] if args[0] != "plan" and args[0] != "report" else "\n".join(out))


def junit(path: Path, passed: list[str], failed: list[str] = []) -> Path:  # noqa: B006
    cases = "".join(
        f'<testcase classname="{t.removesuffix(".py").replace("/", ".")}" name="t" file="{t}"/>'
        for t in passed
    ) + "".join(
        f'<testcase classname="{t.removesuffix(".py").replace("/", ".")}" name="t" file="{t}">'
        "<failure message='x'/></testcase>"
        for t in failed
    )
    path.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>", encoding="utf-8")
    return path


def test_a_closure_is_exactly_what_selection_would_run_for_each_file(
    make_repo: RepoFactory,
) -> None:
    root = make_repo(SOURCES)
    repo = open_repository(root)
    state = repo.test_graph_state()
    closures = repo.input_closures()
    unbounded = {test for test, closure in closures.items() if closure.unbounded is not None}
    for path in sorted(state.checkout.all_files):
        selected = set(repo.select_tests([path]).tests) - unbounded
        inverse = {t for t, c in closures.items() if path in c.files and t not in unbounded}
        assert selected == inverse, path


def test_what_a_test_reads_decides_whether_its_inputs_are_bounded(make_repo: RepoFactory) -> None:
    root = make_repo(SOURCES)
    repo = open_repository(root)
    state = repo.test_graph_state()
    closures = repo.input_closures()
    assert closures["pkg/tests/test_calc.py"].unbounded is None
    assert closures["pkg/tests/test_calc.py"].files >= {"pkg/calc.py", "uv.lock", "settings.cfg"}
    assert "scripts/tool.py" not in closures["pkg/tests/test_calc.py"].files
    assert "scripts/tool.py" in closures["tests/test_scratch.py"].files
    assert "pkg/data/table.csv" in closures["pkg/tests/test_resource.py"].files
    assert closures["pkg/tests/test_resource.py"].unbounded is None
    assert closures["tests/test_scratch.py"].unbounded is None
    unanchored = closures["tests/test_repo_read.py"]
    assert unanchored.unbounded == "unanchored-read:tests/test_repo_read.py"
    assert unanchored.files == state.checkout.all_files


def test_reading_a_path_selection_cannot_see_does_not_change_what_selection_does(
    make_repo: RepoFactory,
) -> None:
    root = make_repo(SOURCES)
    repo = open_repository(root)
    assert "tests/test_repo_read.py" in repo.test_lanes().static
    assert "tests/test_repo_read.py" not in repo.select_tests(["pkg/calc.py"]).tests
    assert "tests/test_repo_read.py" in repo.select_tests(["tests/test_repo_read.py"]).tests


def test_a_plan_follows_the_content_of_a_closure_and_nothing_else(
    make_repo: RepoFactory, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(SOURCES)
    first = cached(root, capsys, "plan")
    assert first["skippable"] == []
    keys = first["keys"]
    assert isinstance(keys, dict)
    assert first["uncacheable"] == {"tests/test_slow.py": "marker:network"}
    (root / "scripts/tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    unrelated = cached(root, capsys, "plan")["keys"]
    assert isinstance(unrelated, dict)
    assert unrelated["pkg/tests/test_calc.py"] == keys["pkg/tests/test_calc.py"]
    assert unrelated["tests/test_repo_read.py"] != keys["tests/test_repo_read.py"]
    (root / "pkg/calc.py").write_text("def double(x: int) -> int:\n    return 2 * x\n", "utf-8")
    edited = cached(root, capsys, "plan")["keys"]
    assert isinstance(edited, dict)
    assert edited["pkg/tests/test_calc.py"] != keys["pkg/tests/test_calc.py"]
    assert edited["tests/test_scratch.py"] == unrelated["tests/test_scratch.py"]


def test_the_environment_the_arguments_and_the_lane_are_part_of_the_key(
    make_repo: RepoFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(SOURCES)
    base = cached(root, capsys, "plan")["keys"]
    assert isinstance(base, dict)
    for extra in (["--env", "IMAGE=b"], ["--pytest-arg=-m", "--pytest-arg=slow"]):
        other = cached(root, capsys, "plan", *extra)["keys"]
        assert isinstance(other, dict)
        assert other["pkg/tests/test_calc.py"] != base["pkg/tests/test_calc.py"], extra
    same = cached(root, capsys, "plan", "--pytest-arg=-q", "--pytest-arg=pkg/tests/test_calc.py")
    assert isinstance(same["keys"], dict)
    assert same["keys"]["pkg/tests/test_calc.py"] == base["pkg/tests/test_calc.py"]


def test_only_a_pass_is_recorded_and_a_recorded_pass_skips_until_something_changes(
    make_repo: RepoFactory, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(SOURCES)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(cached(root, capsys, "plan")), encoding="utf-8")
    report = junit(
        tmp_path / "junit.xml",
        ["pkg/tests/test_calc.py", "tests/test_scratch.py", "tests/test_slow.py"],
        failed=["pkg/tests/test_resource.py"],
    )
    recorded = cached(root, capsys, "record", "--plan", str(plan), "--junit", str(report))
    assert recorded["tests"] == ["pkg/tests/test_calc.py", "tests/test_scratch.py"]
    second = cached(root, capsys, "plan")
    assert second["skippable"] == ["pkg/tests/test_calc.py", "tests/test_scratch.py"]
    assert isinstance(second["run"], list)
    assert "pkg/tests/test_calc.py" not in second["run"]
    (root / "pkg/calc.py").write_text("def double(x: int) -> int:\n    return x + x\n", "utf-8")
    third = cached(root, capsys, "plan")
    assert third["skippable"] == ["tests/test_scratch.py"]


def test_a_skippable_test_that_failed_is_reported_and_strict_fails_the_run(
    make_repo: RepoFactory, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(SOURCES)
    first = tmp_path / "plan.json"
    first.write_text(json.dumps(cached(root, capsys, "plan")), encoding="utf-8")
    ok = junit(tmp_path / "ok.xml", ["pkg/tests/test_calc.py"])
    cached(root, capsys, "record", "--plan", str(first), "--junit", str(ok))
    again = tmp_path / "again.json"
    again.write_text(json.dumps(cached(root, capsys, "plan")), encoding="utf-8")
    bad = junit(tmp_path / "bad.xml", [], failed=["pkg/tests/test_calc.py"])
    durations = tmp_path / "durations.json"
    durations.write_text('{"pkg/tests/test_calc.py": 4.5}', encoding="utf-8")
    report = cached(root, capsys, "report", "--plan", str(again), "--junit", str(bad))
    assert report["would_skip_failed"] == ["pkg/tests/test_calc.py"]
    args = ["--repo", str(root), "test-cache", "report", "--plan", str(again), "--junit", str(bad)]
    assert main([*args, "--strict"]) == 1
    capsys.readouterr()
    good = junit(tmp_path / "good.xml", ["pkg/tests/test_calc.py"])
    saved = cached(
        root, capsys, "report", "--plan", str(again), "--junit", str(good),
        "--durations", str(durations),
    )  # fmt: skip
    assert saved["would_skip_passed"] == 1
    assert saved["saved_seconds"] == 4.5


def test_passes_travel_between_checkouts_as_lines_and_expire(
    make_repo: RepoFactory, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(SOURCES)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(cached(root, capsys, "plan")), encoding="utf-8")
    ok = junit(tmp_path / "ok.xml", ["pkg/tests/test_calc.py"])
    cached(root, capsys, "record", "--plan", str(plan), "--junit", str(ok))
    assert main(["--repo", str(root), "test-cache", "export"]) == 0
    exported = capsys.readouterr().out
    assert len(exported.splitlines()) == 1
    lines = tmp_path / "passes.jsonl"
    lines.write_text(exported, encoding="utf-8")
    other = tmp_path / "clone"
    commit(root)
    git(tmp_path, "clone", "-q", str(root), str(other))
    assert cached(other, capsys, "plan")["skippable"] == []
    assert cached(other, capsys, "import", str(lines))["imported"] == 1
    assert cached(other, capsys, "plan")["skippable"] == ["pkg/tests/test_calc.py"]
    assert cached(other, capsys, "plan", "--ttl-days", "-1")["skippable"] == []
    assert cached(other, capsys, "prune", "--ttl-days", "-1")["pruned"] == 1
    assert cached(other, capsys, "plan")["skippable"] == []


def test_a_host_supplies_the_closures_its_own_selection_knows(
    make_repo: RepoFactory, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(SOURCES)
    closures = tmp_path / "closures.json"
    closures.write_text(
        json.dumps({"pkg/tests/test_calc.py": {"files": ["pkg/calc.py"], "unbounded": None}}),
        encoding="utf-8",
    )
    narrow = cached(root, capsys, "plan", "--closures-file", str(closures))
    assert isinstance(narrow["keys"], dict)
    assert list(narrow["keys"]) == ["pkg/tests/test_calc.py"]
    assert isinstance(narrow["uncacheable"], dict)
    assert set(narrow["uncacheable"]) >= {"pkg/tests/test_resource.py"}


def test_a_test_in_the_native_lane_is_never_cached(
    make_repo: RepoFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(SOURCES)
    plan = cached(root, capsys, "plan")
    assert "tests/test_db.py" not in plan["keys"]  # type: ignore[operator]
    native = cached(root, capsys, "plan", "--lane", "native")
    assert native["uncacheable"] == {"tests/test_db.py": "native-lane:fixture:db_url"}
