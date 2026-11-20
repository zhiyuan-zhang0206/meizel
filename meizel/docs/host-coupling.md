# meizel/ — Remaining Host-Specific Knowledge

The code under `meizel/` is not yet free of this repository: the places below still name its paths,
fixtures, roles or vocabulary. This is the work list for the next decoupling change, not a statement
of what is acceptable; each entry should move to the policy, to a manifest, or to the host's own
tooling. Paths are non-test code and lines are those of the commit that wrote the list.

- Test selection (`meizel/test_graph/`):
  - `impact.py:24-37` `TREE_SCAN_PINS`, eleven Meiva test paths; `impact.py:40-49`
    `_GLOBAL_NAMES` (`uv.lock`, `.github/workflows/ci.yml`); `impact.py:161` `schedules`,
    `impact.py:170` `ui/` and `impact.py:179` `.github/actions/`; `impact.py:259` and `:273`,
    `checkout_plan.py:28` and `:89`, `meizel/checkout.py:710` and `:715`: the `tests/e2e/` layout.
  - `lanes.py:25-47` fixture names of the host's database and bus (`gateway_data_plane`,
    `cluster_defaults_unset`, `aops_pool`, `aredis_inbound_listener`, `postgres_access`,
    `redis_access`, ...), `lanes.py:49` `NATIVE_MARKERS` (`native_permissions_helper`) and
    `lanes.py:51-59` `NATIVE_MODULES`.
- Contracts: `contracts/enumerations.py:190` `_outside_rule` (`meizel/`, `docs/`);
  `contracts/ambient_read.py:50` `_GOVERNED_ROLES`, the host's role vocabulary.
- Paths of the host's tooling: `lint_common.py:67-74` (`scripts/lint/`, `scripts/structure/`, ...);
  `language/purity.py:72` (`scripts/<top>.py`); `language/python_commands.py:8`;
  `graph/python_layout.py:176-183` (the standalone-project CI contract: `uv.lock`, a `cpu` extra).
- Documentation paths in diagnostics: `budgets/budget_plans.py` and `language/scan.py` point at
  `docs/conventions/python-conventions.md`.

The rules that were the host's own (single decision owners, the clock lattice, the timing judgement,
ambient state, the `Settings` rules, the machine-role reader, path imports and the script-sibling
guard) left this package for the host in 0.2.0, and the policy tables they read are declared by the
host under `[sections]`.

Parent: [the meizel node](meizel.md).
