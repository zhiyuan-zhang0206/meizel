"""meizel's public API: what a host's own tooling may import.

The names here follow the package version: a release that removes one or changes what it means is a
new major version (minor, while the major is 0), and a release that adds one is a new minor version.
Every other module of the package is internal and may change in any release. A host's rules (the
`[sections]` tables of `meizel.policy.toml`) read their policy through `allowances`, judge a
checkout through `SourceTree` and `GitRepo`, and share the scan vocabulary of `lint_common`.
"""

from __future__ import annotations

from meizel import allowances, lint_common
from meizel.allowances import POLICY, Declaration, Policy, RemovalReport, removal_report
from meizel.budgets import limits
from meizel.budgets.budget_plans import tracked_children
from meizel.checkout import (
    GitRepo,
    apply_plan,
    lanes_at,
    load_universe,
    python_reverse_closure_at,
    roles_at,
    source_tree,
    toplevel,
    tracked_files,
)
from meizel.contracts.analysis import (
    Analysis,
    analyze,
    exempt_test_modules,
    load_manifests,
    load_policy,
    type_checking_in_scope,
    type_checking_violations,
)
from meizel.contracts.enumerations import parse_regions
from meizel.contracts.sync import prepare_policy_snapshot
from meizel.entry import main, open_repository
from meizel.graph.model import Fact, FactKind, MeizelError, Sources
from meizel.graph.universe import EditPlan, SourceTree, Universe
from meizel.language.python import scan_tree
from meizel.language.typescript import typescript_files
from meizel.roles import (
    all_packages,
    framework_dirs,
    parse_roles,
    pytest_test_hosts,
    select_packages,
)
from meizel.source_text import is_mapping, is_object_list, object_of
from meizel.test_graph.cutoff import package_local_tests
from meizel.test_graph.impact import propagate_test_consumers

__all__ = [
    "POLICY",
    "Analysis",
    "Declaration",
    "EditPlan",
    "Fact",
    "FactKind",
    "GitRepo",
    "MeizelError",
    "Policy",
    "RemovalReport",
    "SourceTree",
    "Sources",
    "Universe",
    "all_packages",
    "allowances",
    "analyze",
    "apply_plan",
    "exempt_test_modules",
    "framework_dirs",
    "is_mapping",
    "is_object_list",
    "lanes_at",
    "limits",
    "lint_common",
    "load_manifests",
    "load_policy",
    "load_universe",
    "main",
    "object_of",
    "open_repository",
    "package_local_tests",
    "parse_regions",
    "parse_roles",
    "prepare_policy_snapshot",
    "propagate_test_consumers",
    "pytest_test_hosts",
    "python_reverse_closure_at",
    "removal_report",
    "roles_at",
    "scan_tree",
    "select_packages",
    "source_tree",
    "toplevel",
    "tracked_children",
    "tracked_files",
    "type_checking_in_scope",
    "type_checking_violations",
    "typescript_files",
]
