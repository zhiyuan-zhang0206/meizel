# The restricted TypeScript subset through the whole check: the code, the debt it can be recorded as,
# and the two declarations that exempt some of its forms. These need the real Node producer, so
# they run in the static lane with the other compiler contracts.
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from meizel.tests.synthetic import (
    RepoFactory,
    diagnostics,
    git,
    record,
    run,
    verdict,
    write,
)

EVAL = "export const run = (code: string) => eval(code);\n"
STAR = "export * from './dep';\n"
KEY = "export const read = (key: string) => globalThis[key];\n"
DEP = "export const dep = 1;\n"


def _repo(make_repo: RepoFactory, files: dict[str, str]) -> Path:
    return make_repo({"app/meizel.toml": "# app\n", **files})


def test_a_restricted_form_is_reported_with_its_own_code_and_a_debt_key(
    make_repo: RepoFactory,
) -> None:
    root = _repo(make_repo, {"app/run.ts": EVAL})
    [found] = diagnostics(root, "restricted-typescript")
    assert (found.path, found.line) == ("app/run.ts", 1)
    assert found.message == "eval of source text is outside the restricted TypeScript subset"
    assert found.debt is not None and found.debt.owner == "app"
    assert not diagnostics(root, "restricted-python")


def test_a_restricted_form_is_recorded_as_debt_and_pruned_when_repaid(
    make_repo: RepoFactory,
) -> None:
    root = _repo(make_repo, {"app/run.ts": EVAL})
    assert run(root, "check") == 1
    assert record(root, "app") == 0
    git(root, "add", "-A")
    assert run(root, "check") == 0
    table = tomllib.loads((root / "app/meizel.toml").read_text())["debt"]
    assert list(table["restricted-typescript"]) == ["run.ts#eval of source text"]
    write(root, {"app/run.ts": "export const run = (code: string) => code;\n"})
    assert run(root, "debt", "prune") == 0
    assert "restricted-typescript" not in tomllib.loads((root / "app/meizel.toml").read_text()).get(
        "debt", {}
    )


def test_a_computed_loader_is_the_same_restricted_form_and_no_longer_an_unresolved_import(
    make_repo: RepoFactory,
) -> None:
    root = _repo(
        make_repo, {"app/load.ts": "export const load = (name: string) => import(name);\n"}
    )
    [found] = diagnostics(root, "restricted-typescript")
    assert found.debt is not None
    assert "import() 'computed target'" in found.message
    assert not diagnostics(root, "unresolved-import")


@pytest.mark.parametrize(
    ("source", "declaration"),
    [
        (EVAL, '[external]\n"run.ts" = "runs the snippet the operator wrote"\n'),
        (KEY, '[dynamic-attrs]\n"run.ts" = "reads the global the operator names"\n'),
    ],
)
def test_external_and_dynamic_attrs_declarations_exempt_their_forms(
    make_repo: RepoFactory, source: str, declaration: str
) -> None:
    root = make_repo({"app/meizel.toml": declaration, "app/run.ts": source})
    assert not verdict(root)
    assert run(root, "check") == 0
    write(root, {"app/run.ts": "export const run = (code: string) => code;\n"})
    assert {code for code, _ in verdict(root)} <= {"stale-external", "stale-dynamic-attrs"}
    assert verdict(root)


@pytest.mark.parametrize(
    ("source", "declaration", "stale"),
    [
        (EVAL, '[dynamic-attrs]\n"run.ts" = "reflects"\n', "stale-dynamic-attrs"),
        (KEY, '[external]\n"run.ts" = "runs code"\n', "stale-external"),
    ],
)
def test_a_declaration_for_the_other_kind_does_not_exempt(
    make_repo: RepoFactory, source: str, declaration: str, stale: str
) -> None:
    root = make_repo({"app/meizel.toml": declaration, "app/run.ts": source})
    assert verdict(root) == {("restricted-typescript", "app/run.ts"), (stale, "app/meizel.toml")}


def test_forms_with_no_declaration_cannot_be_exempted(make_repo: RepoFactory) -> None:
    root = _repo(
        make_repo,
        {
            "app/dep.ts": DEP,
            "app/star.ts": STAR,
            "app/ambient.ts": "declare global { interface Window { x: number } }\nexport {};\n",
            "app/meizel.toml": (
                '[external]\n"star.ts" = "x"\n"ambient.ts" = "x"\n'
                '[dynamic-attrs]\n"star.ts" = "x"\n"ambient.ts" = "x"\n'
            ),
        },
    )
    flagged = {d.path for d in diagnostics(root, "restricted-typescript")}
    assert flagged == {"app/star.ts", "app/ambient.ts"}


def test_the_scope_of_the_typescript_policy_bounds_the_new_forms(make_repo: RepoFactory) -> None:
    root = make_repo(
        {
            "app/meizel.toml": "",
            "app/judged/meizel.toml": "",
            "app/judged/run.ts": EVAL,
            "app/other/meizel.toml": "",
            "app/other/run.ts": EVAL,
            "meizel.policy.toml": '[typescript]\nscopes = ["app/judged"]\n',
        }
    )
    assert {d.path for d in diagnostics(root, "restricted-typescript")} == {"app/judged/run.ts"}


@pytest.mark.parametrize("extension", ["py", "ts"])
def test_both_languages_report_restricted_forms_under_their_own_code(
    make_repo: RepoFactory, extension: str
) -> None:
    source = "exec('1')\n" if extension == "py" else "eval('1');\n"
    code = "restricted-python" if extension == "py" else "restricted-typescript"
    root = _repo(make_repo, {f"app/run.{extension}": source})
    [found] = diagnostics(root, code)
    assert found.path == f"app/run.{extension}" and found.debt is not None
    assert run(root, "check") == 1
    assert record(root, "app") == 0
    git(root, "add", "-A")
    assert run(root, "check") == 0


@pytest.mark.parametrize("extension", ["py", "ts"])
def test_both_languages_exempt_source_text_under_external(
    make_repo: RepoFactory, extension: str
) -> None:
    source = "exec('1')\n" if extension == "py" else "eval('1');\n"
    root = make_repo(
        {
            "app/meizel.toml": f'[external]\n"run.{extension}" = "runs the operator\'s snippet"\n',
            f"app/run.{extension}": source,
        }
    )
    assert run(root, "check") == 0
