# meizel/ — Remaining Host-Specific Knowledge

The code under `meizel/` is not yet free of this repository: the places below still name its paths,
fixtures, roles or vocabulary. This is the work list for the next decoupling change, not a statement
of what is acceptable; each entry should move to the policy, to a manifest, or to the host's own
tooling. Paths are non-test code and lines are those of the commit that wrote the list.

- Contracts: `contracts/enumerations.py:190` `_outside_rule` (`meizel/`, `docs/`);
  `contracts/ambient_read.py:50` `_GOVERNED_ROLES`, the host's role vocabulary.
- Paths of the host's tooling: `language/python/purity.py:72` (`scripts/<top>.py`); `language/python/python_commands.py:8`;
  `language/python/resolve/layout.py:176-183` (the standalone-project CI contract: `uv.lock`, a `cpu` extra).
- Documentation paths in diagnostics: `budgets/budget_plans.py` and `language/python/scanner.py` point at
  `docs/conventions/python-conventions.md`.

The rules that were the host's own (single decision owners, the clock lattice, the timing judgement,
ambient state, the `Settings` rules, the machine-role reader, path imports and the script-sibling
guard) left this package for the host in 0.2.0, and the policy tables they read are declared by the
host under `[sections]`. What test selection knew about the host (the native fixtures, markers and
modules, the tree-scan tests, the global, frontend and excluded paths, the documentation roots) is
the `[test-graph]` table of the policy since 0.3.0.

Parent: [the meizel node](meizel.md).
