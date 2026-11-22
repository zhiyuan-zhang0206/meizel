# meizel

**Machine-checked architecture that only tightens, for codebases that AI agents change.**

When people write the code, architecture survives through review and shared understanding. When
agents write much of it, there is no shared understanding to rely on, and review cannot keep up with
the output. meizel keeps the architecture as data in the repository and checks every change against
it in CI. A known violation is recorded as debt with an exit condition, so the record can shrink and
never grow.

Module-boundary checkers (import-linter, tach, eslint-plugin-boundaries, Nx module boundaries) cover
the first of the pieces below. meizel adds two more and puts them over one dependency graph for
several languages: the purity rules, which turn "functional core, imperative shell" into a check,
and the debt ledger. It is not a build system, a general lint collection or a formatter.

meizel checks the structure of a repository from data the repository keeps beside its code:

- **Module manifests** (`meizel.toml` in each directory): what a directory exports and which sibling
  each child may use. The import graph has to match what the manifests declare, and the declared
  graph has to stay a DAG.
- **Ambient-state and purity rules**: in a strict module, code may not read the clock, the
  environment, the working directory or the filesystem itself. Those reads happen once, in a
  declared composition root (`[roots]`), and the values are passed down.
- **Recorded debt**: each known violation is written down with an exit condition. A new violation
  fails the check, and a repaid one has to be pruned from the record.
- **Budgets**: a ceiling on lines per file and on entries per directory.
- **Test selection**: picks the tests a change can affect, from the import graph and the test facts.

It analyzes Python with the standard library's `ast`, and TypeScript with the TypeScript compiler
through a small Node adapter. Each language is a frontend a repository can switch off:
`[languages] enabled = ["python"]` in `meizel.policy.toml` reads Python only and needs no Node.

## Install

meizel has no runtime Python dependencies. It runs on Python 3.12: its standard-library tables (which
modules are the standard library's, and what each public name of `os`, `time`, `pathlib`, ... reads)
are judged on that interpreter, and it refuses to run on another rather than judge new names by a
default.

meizel is not on PyPI. Use it as a git dependency pinned to a release tag or commit, for example in
a project managed by uv:

```toml
[dependency-groups]
dev = ["meizel @ git+https://github.com/zhiyuan-zhang0206/meizel@v0.12.1"]
```

## Use

Run it from the root of the repository you want to check:

```sh
python -m meizel check            # the whole repository
python -m meizel check --changed  # only what differs from the default base
python -m meizel --help
```

The repository declares its top-level roles in a root `meizel.toml`:

```toml
[roles]
application = ["myapp"]
tests = ["tests"]
tooling = ["scripts"]
```

Everything the checker allows by exception lives in `meizel.policy.toml`, each entry with its reason.
A repository's own rules keep their exemptions in the same file and declare the shape of their tables
under `[sections]`; what test selection should know about the repository's tests (native fixtures,
paths whose change runs everything) is its `[test-graph]` table.

### Writing your own rules

Import from `meizel.api` only. Its names follow the version: removing or changing one is a breaking
release, adding one is a minor release. Every other module is internal.

### TypeScript

TypeScript analysis uses the compiler of the project that installed meizel, which is the directory
holding the environment (`<project>/.venv`). That project names its Node package in its own policy,
and the package must be installed with pnpm, hoisted, from its lockfile:

```toml
[typescript]
package-dir = ["web"]
```

## Develop

```sh
uv sync
(cd toolchain && pnpm install --frozen-lockfile)   # the compiler meizel's own TypeScript tests use
uv run pytest -n auto
uv run basedpyright meizel
uv run ruff check meizel && uv run ruff format --check meizel
uv run python -m meizel check                      # meizel checks itself
```

`meizel/docs/` holds the design notes for each rule. Some of them still point into the repository
meizel was extracted from, and `meizel/docs/host-coupling.md` lists the code that still assumes
that repository's layout.
