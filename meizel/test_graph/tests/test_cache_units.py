"""The pure parts of the test result cache: arguments, junit, policy and the unanchored-read flag."""

from __future__ import annotations

import pytest

from meizel.test_graph import (
    CachePolicy,
    normalize_pytest_args,
    outcomes_from_junit,
    scan_raw_test_facts,
)
from meizel.test_graph.model import FACT_UNANCHORED_READ


@pytest.mark.parametrize(
    ("source", "flagged"),
    [
        ("def t():\n    open('x.txt').read()\n", True),
        ("from pathlib import Path\ndef t():\n    Path('d').rglob('*.py')\n", True),
        ("import os\ndef t():\n    os.listdir('.')\n", True),
        ("import os\ndef t():\n    os.getcwd()\n", True),
        ("def t(tmp_path):\n    (tmp_path / 'a').read_text()\n", False),
        ("def t(tmp_path):\n    d = tmp_path / 'a'\n    open(d / 'b')\n", False),
        ("def t(tmp_path_factory):\n    base = tmp_path_factory.mktemp('x')\n    open(base)\n", False),
        ("from pathlib import Path\nHERE = Path(__file__).parents[0]\ndef t():\n    (HERE / 'a').read_text()\n", False),
        ("def t():\n    return 1\n", False),
    ],
)  # fmt: skip
def test_a_read_of_a_path_the_file_does_not_anchor_is_flagged(source: str, flagged: bool) -> None:
    facts = scan_raw_test_facts("pkg/tests/test_x.py", source)
    assert bool(facts.flags & FACT_UNANCHORED_READ) is flagged


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        (["-q", "-n", "4", "--dist=loadfile", "tests/test_a.py"], ()),
        (["-n4", "--junit-xml=out.xml", "-o", "junit_family=xunit1"], ()),
        (["-m", "not flaky", "-n", "4", "pkg/tests/test_a.py::test_b"], ("-m", "not flaky")),
        (["--omit-static-tests", "-o", "addopts="], ("--omit-static-tests", "-o", "addopts=")),
        (["--unknown", "value"], ("--unknown", "value")),
    ],
)
def test_only_options_that_decide_what_runs_are_part_of_a_key(
    given: list[str], kept: tuple[str, ...]
) -> None:
    assert normalize_pytest_args(given) == kept


def test_junit_names_a_file_by_its_attribute_or_by_the_class_it_holds() -> None:
    tests = {"pkg/tests/test_a.py", "pkg/tests/test_b.py", "tests/test_c.py"}
    report = (
        "<testsuites><testsuite>"
        '<testcase classname="pkg.tests.test_a.TestX" name="t1"/>'
        '<testcase classname="pkg.tests.test_a.TestX" name="t2"><skipped/></testcase>'
        '<testcase classname="pkg.tests.test_b" name="t" file="pkg/tests/test_b.py"><error/></testcase>'
        '<testcase classname="" name="tests/test_c.py"><error/></testcase>'
        '<testcase classname="elsewhere" name="t"/>'
        "</testsuite></testsuites>"
    )
    assert outcomes_from_junit([report], tests) == {
        "pkg/tests/test_a.py": "passed",
        "pkg/tests/test_b.py": "failed",
        "tests/test_c.py": "failed",
    }


def test_the_policy_declares_variables_and_markers_and_flaky_is_always_one() -> None:
    assert CachePolicy.from_policy_text(None) == CachePolicy()
    declared = CachePolicy.from_policy_text(
        '[test-cache]\nenv = ["B", "A"]\nuncacheable-markers = ["network"]\n'
    )
    assert declared.env == ("A", "B")
    assert declared.uncacheable_markers == {"flaky", "network"}
