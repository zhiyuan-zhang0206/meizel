from __future__ import annotations

from pathlib import Path

import pytest

from meizel import allowances
from meizel.entry import open_repository
from meizel.graph.model import OS_KINDS
from meizel.tests.synthetic import RepoFactory

# The reference host: a snapshot of a working repository's policy.
HOST_POLICY = Path(__file__).resolve().parents[1] / "host/policy.toml"
POLICY = (
    '[sections.ambient-state]\npure-callees = "names"\nwiring-callees = "names"\nsites = "reasons"\n\n'
    '[sections.single-owner]\n"*" = "reasons"\n\n'
    '[ambient-state]\npure-callees = ["re.compile", "typing.TypeVar"]\n\n'
    '[ambient-state.sites]\n"a.py::hidden-cache:f" = "a pure derivation"\n\n'
    '[single-owner.postgres-dial]\n"b.py" = "cannot go through the owner"\n'
)


def test_a_rule_reads_its_sections_from_the_policy(make_repo: RepoFactory) -> None:
    policy = allowances.load(open_repository(make_repo({"meizel.policy.toml": POLICY})))
    assert policy.names("ambient-state", "pure-callees") == ("re.compile", "typing.TypeVar")
    assert policy.reasons("ambient-state", "sites") == {"a.py::hidden-cache:f": "a pure derivation"}
    assert policy.reasons("single-owner", "postgres-dial") == {
        "b.py": "cannot go through the owner"
    }


def test_a_section_the_file_does_not_have_lists_nothing(make_repo: RepoFactory) -> None:
    policy = allowances.load(open_repository(make_repo({"meizel.policy.toml": POLICY})))
    assert policy.names("ambient-state", "wiring-callees") == ()
    assert policy.reasons("type-checking", "files") == {}


def test_an_absent_policy_lists_nothing(make_repo: RepoFactory) -> None:
    root = make_repo({"a.py": ""})
    (root / allowances.POLICY).unlink(missing_ok=True)
    assert allowances.load(open_repository(root)).reasons("type-checking", "files") == {}


@pytest.mark.parametrize(
    ("rule", "section", "shape"),
    [
        ("ambient-state", "no-such-section", "reasons"),
        ("ambient-state", "pure-callees", "reasons"),
        ("type-checking", "files", "names"),
        ("single-owner", "postgres-dial", "names"),
    ],
)
def test_a_rule_cannot_ask_for_a_section_that_does_not_exist(
    make_repo: RepoFactory, rule: str, section: str, shape: str
) -> None:
    policy = allowances.load(open_repository(make_repo({"meizel.policy.toml": POLICY})))
    with pytest.raises(KeyError):
        (policy.reasons if shape == "reasons" else policy.names)(rule, section)


def test_a_malformed_policy_is_an_error_for_the_rule_that_reads_it(make_repo: RepoFactory) -> None:
    root = make_repo({"meizel.policy.toml": '[type-checking.files]\n"a.py" = ""\n'})
    with pytest.raises(
        ValueError, match=r"\[type-checking.files\] 'a.py' needs a non-empty reason"
    ):
        allowances.load(open_repository(root))


def test_the_repository_policy_is_well_formed() -> None:
    _, problems = allowances.parse(HOST_POLICY.read_text(encoding="utf-8"))
    assert problems == []


def test_the_keys_of_the_ambient_table_declare_the_state_kinds() -> None:
    text = '[ambient]\nqueue = ["Queue.open()"]\ncache_2 = ["cache"]\n'
    policy, problems = allowances.parse(text)
    assert problems == []
    assert policy.state_kinds == ("queue", "cache_2")
    assert policy.names("ambient", "queue") == ("Queue.open()",)
    assert policy.reader_kinds[-2:] == ("queue", "cache_2")


@pytest.mark.parametrize("kind", OS_KINDS)
def test_a_kind_of_the_standard_library_cannot_be_declared_as_state(kind: str) -> None:
    policy, problems = allowances.parse(f'[ambient]\n{kind} = ["thing()"]\n')
    assert policy.state_kinds == ()
    assert [problem.split(" is a kind of the standard library")[0] for problem in problems] == [
        f"[ambient] {kind!r}"
    ]


@pytest.mark.parametrize("kind", ["Queue", "2fast", "has-dash", "has space"])
def test_a_state_kind_is_a_lowercase_name(kind: str) -> None:
    policy, problems = allowances.parse(f'[ambient]\n"{kind}" = ["thing()"]\n')
    assert policy.state_kinds == ()
    assert len(problems) == 1
    assert "must be a lowercase kind name" in problems[0]


def test_readers_are_listed_under_a_declared_state_kind_and_under_no_other() -> None:
    readers = '[ambient-readers.queue]\n"lib.queue.open()" = "opens the broker"\n'
    declared, problems = allowances.parse("[ambient]\nqueue = []\n" + readers)
    assert problems == []
    assert declared.reasons("ambient-readers", "queue") == {"lib.queue.open()": "opens the broker"}
    undeclared, problems = allowances.parse(readers)
    assert undeclared.state_kinds == ()
    assert len(problems) == 1
    assert "no section 'queue'" in problems[0]


def test_a_retired_state_kind_is_not_built_into_the_checker() -> None:
    assert "endpoints" not in allowances.RULES["ambient-readers"]
    assert allowances.parse('[ambient-readers.endpoints]\n"a.b()" = "reads"\n')[1]


def test_the_public_surface_names_come_from_the_policy() -> None:
    policy, problems = allowances.parse('[public-surface]\nnames = ["__exports__"]\n')
    assert problems == []
    assert policy.names("public-surface", "names") == ("__exports__",)
    assert allowances.parse("")[0].names("public-surface", "names") == ()


# A host rule's tables are read once `[sections]` declares their shape: names lists and reasons tables
# by section, and `"*"` for a reasons table per governed name.
DECLARED_HOST = (
    '[sections.clock-lattice]\nfamily-modules = "names"\nindependent-clocks = "reasons"\n\n'
    '[sections.single-owner]\n"*" = "reasons"\n\n'
    '[clock-lattice]\nfamily-modules = ["base/timing.py"]\n\n'
    '[clock-lattice.independent-clocks]\nSTALL_S = "its own clock"\n\n'
    '[single-owner.postgres-dial]\n"b.py" = "cannot go through the owner"\n'
)


def test_a_declared_host_rule_is_read_like_a_checker_rule() -> None:
    policy, problems = allowances.parse(DECLARED_HOST)
    assert problems == []
    assert policy.names("clock-lattice", "family-modules") == ("base/timing.py",)
    assert policy.reasons("clock-lattice", "independent-clocks") == {"STALL_S": "its own clock"}
    assert policy.reasons("single-owner", "postgres-dial") == {
        "b.py": "cannot go through the owner"
    }


def test_an_undeclared_host_table_is_refused() -> None:
    problems = allowances.parse('[clock-lattice]\nfamily-modules = ["base/timing.py"]\n')[1]
    assert any("[sections]" in problem for problem in problems)


@pytest.mark.parametrize(
    "declaration",
    [
        '[sections.purity]\nfiles = "reasons"\n',
        '[sections.external]\nfiles = "reasons"\n',
        '[sections.Bad_Name]\nfiles = "reasons"\n',
        '[sections.mine]\nfiles = "readers"\n',
    ],
)
def test_a_declaration_cannot_take_a_checker_table_or_an_unknown_shape(declaration: str) -> None:
    assert allowances.parse(declaration)[1]


def test_a_section_the_declaration_does_not_name_is_refused() -> None:
    text = '[sections.mine]\nfiles = "reasons"\n\n[mine]\nother = []\n'
    assert any("has no section 'other'" in problem for problem in allowances.parse(text)[1])


# The declarations a change takes away, and the `Policy-Removal` line that answers them.
ALLOWANCES = allowances.Policy(
    external={"app/runner.py": "executes the schedule script the user wrote"},
    loads={"schedules/jobs/dry_import_child.py": ("schedules", "meiva")},
    default_arguments=("clock",),
    listed={("ambient-readers", "environ"): {"pkg.env.read()": "reads os.environ"}},
    named={("ambient-state", "sink-callees"): ("sink", "sink_now")},
)
_SEPARATOR = " \u2014 "


def _without(
    *,
    external: dict[str, str] | None = None,
    loads: dict[str, tuple[str, ...]] | None = None,
    default_arguments: tuple[str, ...] | None = None,
    listed: dict[tuple[str, str], dict[str, str]] | None = None,
    named: dict[tuple[str, str], tuple[str, ...]] | None = None,
) -> allowances.Policy:
    return allowances.Policy(
        external=ALLOWANCES.external if external is None else external,
        loads=ALLOWANCES.loads if loads is None else loads,
        default_arguments=ALLOWANCES.default_arguments
        if default_arguments is None
        else default_arguments,
        listed=ALLOWANCES.listed if listed is None else listed,
        named=ALLOWANCES.named if named is None else named,
    )


def _removal(
    declared: str,
    why: str = "the site is gone with its module",
    gap: str = "nothing reads it now",
) -> str:
    return f"Policy-Removal: {declared}{_SEPARATOR}{why}{_SEPARATOR}{gap}"


def test_a_removed_entry_is_one_declaration() -> None:
    report = allowances.removal_report(
        ALLOWANCES, _without(external={"other.py": "runs external code"}), ""
    )
    assert [item.named for item in report.removed] == ["external.app/runner.py"]
    assert [item.named for item in report.added] == ["external.other.py"]


def test_a_shortened_list_loses_exactly_the_names_it_dropped() -> None:
    after = _without(loads={"schedules/jobs/dry_import_child.py": ("schedules",)})
    report = allowances.removal_report(ALLOWANCES, after, "")
    assert [item.named for item in report.removed] == [
        "loads.schedules/jobs/dry_import_child.py -> meiva"
    ]


def test_a_deleted_section_loses_every_name_it_held() -> None:
    report = allowances.removal_report(ALLOWANCES, _without(named={}), "")
    assert [item.named for item in report.removed] == [
        "ambient-state.sink-callees.sink",
        "ambient-state.sink-callees.sink_now",
    ]


def test_a_rewritten_reason_is_not_a_removal() -> None:
    after = _without(external={"app/runner.py": "runs the script the operator names"})
    report = allowances.removal_report(ALLOWANCES, after, "")
    assert (report.removed, report.added) == ((), ())


def test_a_shortened_default_arguments_list_is_a_removal() -> None:
    report = allowances.removal_report(ALLOWANCES, _without(default_arguments=()), "")
    assert [item.named for item in report.removed] == ["default-arguments.clock"]


@pytest.mark.parametrize(
    ("text", "declared"),
    [
        (
            _removal("ambient-readers.environ.pkg.env.read()"),
            "ambient-readers.environ.pkg.env.read()",
        ),
        (_removal("AMBIENT-READERS.ENVIRON"), "AMBIENT-READERS.ENVIRON"),
        (
            "policy-removal:ambient-readers.environ"
            + _SEPARATOR
            + "no reader is left"
            + _SEPARATOR
            + "nothing reads it",
            "ambient-readers.environ",
        ),
    ],
    ids=["entry", "case", "no-space-after-the-colon"],
)
def test_a_declaration_is_read_with_its_three_fields(text: str, declared: str) -> None:
    report = allowances.removal_report(ALLOWANCES, ALLOWANCES, text)
    assert report.problems == ()
    assert [line.declared for line in report.declared] == [declared]
    assert report.declared[0].why
    assert report.declared[0].replacement


def test_a_line_with_two_fields_is_a_problem() -> None:
    report = allowances.removal_report(
        ALLOWANCES,
        ALLOWANCES,
        "Policy-Removal: ambient-readers.environ.pkg.env.read()" + _SEPARATOR + "gone",
    )
    assert report.declared == ()
    assert len(report.problems) == 1


@pytest.mark.parametrize(
    "line",
    [
        _removal("ambient-readers.environ", why="<why it is no longer needed>"),
        _removal("ambient-readers.environ", gap="short"),
        _removal("ambient-readers.environ.pkg.env.read()", gap="<the gap>"),
    ],
    ids=["placeholder-why", "too-short", "placeholder-gap"],
)
def test_a_field_left_unanswered_is_a_problem_when_the_line_names_a_removal(line: str) -> None:
    report = allowances.removal_report(ALLOWANCES, _without(listed={}), line)
    assert report.declared == ()
    assert len(report.problems) == 1
    assert len(report.unanswered) == 1


def test_a_quoted_template_answers_nothing_and_is_not_a_problem() -> None:
    template = (
        "Policy-Removal: <table>[.<entry>] — <why it is no longer needed>"
        " — <what replaces it, or the gap it leaves>"
    )
    report = allowances.removal_report(ALLOWANCES, _without(listed={}), template)
    assert (report.declared, report.problems) == ((), ())
    assert len(report.unanswered) == 1


def test_other_lines_are_not_declarations() -> None:
    report = allowances.removal_report(
        ALLOWANCES, ALLOWANCES, "## Why\nThe policy lost an entry.\n# Policy-Removal: ignored\n"
    )
    assert (report.declared, report.problems) == ((), ())


@pytest.mark.parametrize(
    ("declared", "open_"),
    [
        ("ambient-readers.environ.pkg.env.read()", False),
        ("ambient-readers.environ.environ", True),
        ("ambient-readers.environ", False),
        ("ambient-readers", False),
        ("ambient-state", True),
    ],
    ids=["entry", "longer-than-the-table", "table", "rule", "another-rule"],
)
def test_a_line_answers_the_entry_it_names_or_a_table_that_contains_it(
    declared: str, open_: bool
) -> None:
    report = allowances.removal_report(ALLOWANCES, _without(listed={}), _removal(declared))
    assert bool(report.unanswered) is open_
    assert bool(report.unused) is open_


def test_a_line_that_names_the_entry_answers_it() -> None:
    report = allowances.removal_report(
        ALLOWANCES, _without(external={}), _removal("external.app/runner.py")
    )
    assert (report.unanswered, report.unused) == ((), ())


def test_a_template_names_the_entry_alone_or_the_table_that_lost_several() -> None:
    report = allowances.removal_report(ALLOWANCES, _without(named={}, external={}), "")
    assert [line.split(_SEPARATOR)[0] for line in report.templates()] == [
        "Policy-Removal: ambient-state.sink-callees",
        "Policy-Removal: external.app/runner.py",
    ]


def test_a_template_in_the_body_does_not_answer_a_real_removal() -> None:
    template = (
        "Policy-Removal: <table>[.<entry>] — <why it is no longer needed>"
        " — <what replaces it, or the gap it leaves>"
    )
    report = allowances.removal_report(ALLOWANCES, _without(listed={}), template)
    assert report.problems == ()
    assert len(report.unanswered) == 1


@pytest.mark.parametrize(
    ("line", "missing"),
    [
        (
            "Policy-Removal: external.app/runner.py" + _SEPARATOR + "the module moved away",
            "<what replaces it, or the gap it leaves>",
        ),
        (
            "Policy-Removal: external.app/runner.py" + _SEPARATOR + "nothing reads it now",
            "<what replaces it, or the gap it leaves>",
        ),
        (
            "Policy-Removal:"
            + _SEPARATOR
            + "the module moved"
            + _SEPARATOR
            + "nothing replaces it",
            "`<table>[.<entry>]` name",
        ),
    ],
    ids=["one-field", "name-and-one-field", "no-name"],
)
def test_a_line_that_is_not_three_fields_says_which_field_is_missing(
    line: str, missing: str
) -> None:
    report = allowances.removal_report(ALLOWANCES, ALLOWANCES, line)
    assert len(report.problems) == 1
    assert missing in report.problems[0]
    assert "missing" in report.problems[0]


def test_a_table_answer_covers_only_the_leaves_below_it() -> None:
    other = allowances.Policy(
        external=ALLOWANCES.external,
        loads={},
        default_arguments=ALLOWANCES.default_arguments,
        listed=ALLOWANCES.listed,
        named=ALLOWANCES.named,
    )
    report = allowances.removal_report(ALLOWANCES, other, _removal("ambient-readers.environ"))
    assert [item.named for item in report.unanswered] == [
        "loads.schedules/jobs/dry_import_child.py -> meiva",
        "loads.schedules/jobs/dry_import_child.py -> schedules",
    ]


def test_a_rule_answer_does_not_cover_another_rule() -> None:
    report = allowances.removal_report(ALLOWANCES, _without(named={}), _removal("ambient-readers"))
    assert [item.named for item in report.unanswered] == [
        "ambient-state.sink-callees.sink",
        "ambient-state.sink-callees.sink_now",
    ]


def test_an_undeclared_host_rule_lists_nothing() -> None:
    policy, problems = allowances.parse("")
    assert problems == []
    assert policy.reasons("single-owner", "postgres-dial") == {}
    assert policy.names("clock-lattice", "family-modules") == ()
