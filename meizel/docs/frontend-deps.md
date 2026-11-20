# meizel/ — Frontend dependencies the analyzer can trust

The analyzer is a node process that loads the compiler from the installation's own Node package, never
the checked repository's: the checker runs against repositories with no frontend at all, and a tree
next to the inspected code is one more thing that code could change under the analysis. The
installation is the project whose environment installed `meizel` (`<project>/.venv` → `<project>`), and
its `meizel.policy.toml` names the Node package under `[typescript] package-dir` (a project that names
none is its own Node package); `meizel.installation.typescript_toolchain` resolves it once per process
and the node runner hands it to the child as the absolute `MEIZEL_TS_PACKAGE_DIR`. Node says
`Cannot find module 'typescript'` when that tree is absent, and says nothing at all when the tree is
present but was installed for a different lockfile — the second case is the dangerous one: `tsc` and
every checker built on it answer from a dependency graph the lockfile does not describe, so both a red
and a green are untrustworthy.

A tree installed by npm has no `node_modules/.modules.yaml`, which is how one is recognized without
asking pnpm. A pnpm install copies the lockfile it installed into `node_modules/.pnpm/lock.yaml`, so
"was this tree installed for the lockfile the package has" is a byte comparison rather than a
heuristic. The package is installed hoisted (`nodeLinker: hoisted`), so compiler files keep the paths
the analyzer names them by.

```meiva-contract
id = "frontend-deps-verdict"
kind = "invariant"
statement = "A TypeScript answer comes only from the installation's own frontend tree, installed from the lockfile that installation carries: before it starts node the analyzer classifies the toolchain's node_modules as ready, missing, npm-era (present without node_modules/.modules.yaml) or lock-changed (node_modules/.pnpm/lock.yaml absent or different from pnpm-lock.yaml), and a state other than ready raises a refusal naming the state and the command that fixes it instead of running the analyzer; a refusal reaches the process as exit code 3, never 1, so a caller can tell an unready environment from a failed check."
code = ["meizel/language/typescript_compiler/runtime.py:scan_batch", "meizel/frontend_deps.py:classify", "meizel/frontend_deps.py:refusal", "meizel/frontend_deps.py:observe", "meizel/lint_common.py:run_node_analyzer", "meizel/entry.py:main"]
tests = ["meizel/tests/test_lint_common.py::test_each_observation_shape_has_one_verdict", "meizel/tests/test_lint_common.py::test_a_refusal_names_the_command_that_fixes_it", "meizel/tests/test_lint_common.py::test_the_analyzer_refuses_before_it_starts_node", "meizel/tests/test_lint_common.py::test_the_cli_exits_three_when_the_checkout_cannot_be_asked"]
```

| State | Recognized by | Remedy the refusal names |
| --- | --- | --- |
| missing | `<toolchain>/node_modules` is not a directory | `(cd <toolchain> && pnpm install --frozen-lockfile)` |
| npm-era | the directory exists, `node_modules/.modules.yaml` does not | the same command |
| lock-changed | `node_modules/.pnpm/lock.yaml` is absent or differs from `pnpm-lock.yaml` | the same command |

The last two are different problems that look alike in an existing population of checkouts: one is a
tree from another installer, the other a tree from a previous lockfile.

## Exit codes

`meizel` separates a clean run (`0`), findings (`1`) and a tool or usage failure (`2`). A refusal is a
fourth thing — the environment could not answer — so it exits `3`. The pre-push hook turns `3` into a
warning naming CI as the authority instead of blocking the push, the same way it treats a missing
frontend executable; the all-tree comment check exits `3` so CI reports a broken install as itself
rather than as a module-not-found stack.

Parent: [TypeScript compiler analysis](checker/typescript.md).
