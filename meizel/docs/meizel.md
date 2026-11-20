# meizel/ — Locality Rules

## What is it

`meizel/` is the home of the repository's locality rules. It is tooling, not
application code: it depends on the standard library only and never imports an
application package. `scripts/` may import `meizel`; `meizel` never imports
`scripts`.

The checker's vocabulary of ambient kinds belongs to the repository's policy, not to the code. What
a repository alone can say is declared in its `meizel.policy.toml`: the kinds of state it keeps
itself (the keys of `[ambient]`), the functions that read the world for their caller
(`[ambient-readers.<kind>]`), and every exemption. The checker's own vocabulary is the standard
library's (`argv`, `environ`, `clock`, `home`, `cwd`, `platform`, `pid`, `random`), so a repository
with a cache or a queue declares it in its policy and a manifest may name it from then on
([ambient kinds](ambient-kinds.md)). Some tables still name this repository;
they are listed in [the host-coupling node](host-coupling.md).

## Language frontends

Every language the checker reads is a frontend (`meizel/language/frontends.py`), and each is
optional. A frontend owns the files of its language and turns them into `FileScan` records: the
facts (edges, fixtures, loads), purity items, ambient acquisitions, patches and problems of each
file. Everything after that (manifests, the dependency graph, recorded debt, exemptions, budgets,
test selection) reads those records and never the language, which is why Python and TypeScript share
one `check`, one `debt record` and one `debt prune`. The built-in frontends are `python` (the
standard library's `ast`, in process) and `typescript` (the TypeScript compiler, in a Node child
whose result is the same record as JSON, `meizel/language/scan_codec.py`).

A repository chooses its languages in `meizel.policy.toml`:

```toml
[languages]
enabled = ["python"]
```

With the table absent every built-in frontend runs. A repository that enables only `python` never
starts Node and never reads a `.ts` file; a name no frontend answers to is refused with the list of
the ones that exist.

## Top-level packages and their roles

The root `meizel.toml` declares which top-level directories exist and what each is,
once: `[roles]` maps `application`, `standalone`, `templates`, `examples`, `tooling`, `tests` and
`frontend` to directories. Every top-level directory that holds Python (hidden
directories aside) must be listed under exactly one role, and every listed name must
exist; the manifest parser enforces both, and `[roles]` is accepted in the root manifest
only. The read and the decision are separate modules: `meizel.checkout` reads the table
(`read_roles(repo)`, `roles_at(root)`) once per process, at the entry that knows the
repository, and passes the parsed role -> directories mapping down as a value; `meizel.roles`
decides over that mapping without touching a file (`parse_roles(text, label=)`,
`select_packages(declared, *roles)`, `all_packages(declared)`, `check_table(table)`,
`pytest_test_hosts(declared)`). The lists that other files must keep as text (the pytest
`testpaths`, the pyright `include`, the wheel packages, the coverage source and the
package alternations of the pre-commit `files` patterns) sit in marked regions that
`python -m meizel roles write` regenerates. `meizel check`, including `check --changed`,
checks all those regions and other Python or TOML literals that list every package of
a role of three or more. These global `manifest-roles` diagnostics cannot be recorded
as debt. `roles check` remains a focused command using the same rule owner; it has no
separate hook. A new package is declared in one place or the check says where.

`standalone` holds independently installed production Python. Its
[project ownership, imports and independent checks](standalone.md)
keep production governance separate from the root distribution environment.

## Contents

- `graph/`, `language/` and `contracts/` are the checker, documented in
  [the checker node](checker/checker.md): `graph/` holds the model,
  the universe of tracked files, graph algorithms, name scopes and import
  access, and `universe.py` the two handles a decision layer reads a checkout
  with — the `Checkout` protocol and the `SourceTree` its `tree` property
  returns, a frozen dataclass whose reads are function fields, so a module that
  only decides takes one and reads nothing itself; `language/` the restricted
  Python forms, pytest fixture requests, mechanical purity and container-budget
  checks (`purity.py`, `purity_structure.py`) and the file scanner that composes
  them with import access; `contracts/` the
  `meizel.toml` manifests, the rule, analysis, recorded debt, the policy file and the commands
  (`python -m meizel`). The layers form a DAG: `contracts` -> `language` -> `graph`.

- `lint_common.py` — the shared scan vocabulary of the standalone lints: test-path
  detection, scan-root resolution and the `--only` changed-files mode, over the
  `SourceTree` its caller built. Changed-files runs widen to a full scan when
  the lockfile that pins the checker changes, because that changes the verdict of untouched files.
- `budgets/` — the 800-line file ceiling and the 20-entry directory cap: every
  judgment is in `budget_plans.py` (both ceilings, which directory entries are
  candidates, what counts as a Python file, which of a target and a structure
  directory is judged, which directories a target selects with their entry counts,
  what counts as a line, and the wording and order of hard violations), while
  `limits.py` walks and reads the checkout and `directory_budget.py` lists a
  directory and tests a judged path's links. A host's structure gate drives them. Near-cap reporting shares `check`'s changed-only, ten-percent
  headroom summary; it does not add a failure condition.
- `test_graph/` — test selection: the tests a change can affect, from the import graph and the
  scanned test facts (`meizel impacted`, `meizel tests`).

Rules a repository runs from its own gates, rather than through `meizel check`, belong to that
repository. They use this package as a library and keep their exemptions in the same policy file,
declared under `[sections]` ([the policy file](checker/policy/policy.md)).

## Type-only guards

The `type-checking` code, the roles and policy it applies to, and how `diagnose` and the
standalone adapter report it: [the type-only guards
node](type-checking.md).
