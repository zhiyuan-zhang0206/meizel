from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping

from meizel.test_graph.cutoff import package_local_tests
from meizel.test_graph.model import (
    FACT_SYNTAX_ERROR,
    FileTestFacts,
    ModuleTable,
    TestCheckout,
    TestGraphPolicy,
    TestSelection,
)

__all__ = [
    "fixture_dependency_edges",
    "propagate_test_consumers",
    "select_impacted_tests",
    "tree_scan_pins",
]

# meiva:note
# The paths whose change reaches every test in any repository: the test runner's configuration, the
# lockfile, the interpreter pin and the checker's own policy. A repository adds its own under
# `[test-graph] global-files` and `global-prefixes`.
_GLOBAL_NAMES = frozenset(
    {
        "conftest.py",
        "pyproject.toml",
        "pytest.ini",
        "uv.lock",
        ".python-version",
        "meizel.policy.toml",
    }
)


# meiva:note
# Propagates collectable test consumers through forward dependency `edges` (including cycles) via
# integer bitsets, avoiding O(V*E) set-copy blowup on dense module graphs.
def propagate_test_consumers(
    edges: Mapping[str, Iterable[str]],
    tests: frozenset[str],
) -> dict[str, set[str]]:
    ordered = sorted(tests)
    reached = {test: 1 << offset for offset, test in enumerate(ordered)}
    pending = deque(ordered)
    queued = set(ordered)
    while pending:
        source = pending.popleft()
        queued.remove(source)
        consumer_bits = reached[source]
        for dependency in edges.get(source, ()):
            before = reached.get(dependency, 0)
            after = before | consumer_bits
            if before != after:
                reached[dependency] = after
                if dependency not in queued:
                    pending.append(dependency)
                    queued.add(dependency)
    reverse: dict[str, set[str]] = {}
    for dep_path, bits in reached.items():
        names: set[str] = set()
        remaining = bits
        while remaining:
            flag = remaining & -remaining
            names.add(ordered[flag.bit_length() - 1])
            remaining ^= flag
        reverse[dep_path] = names
    return reverse


# meiva:note
# Builds per-test package-init, ancestor `conftest.py`, and `path_scopes.toml` dependency edges.
def fixture_dependency_edges(
    checkout: TestCheckout,
    table: ModuleTable,
) -> tuple[dict[str, set[str]], tuple[tuple[str, str], ...]]:
    tops = checkout.top_packages
    edges: dict[str, set[str]] = {test: set() for test in checkout.collectable}
    missing: list[tuple[str, str]] = []
    for test in checkout.collectable:
        dotted = ".".join(test.removesuffix(".py").split("/"))
        edges[test].update(table.module_files(dotted, tops))
        directory = test.rpartition("/")[0]
        while directory:
            conftest = f"{directory}/conftest.py"
            if conftest in checkout.conftests:
                edges[test].add(conftest)
            directory = directory.rpartition("/")[0]
    for source_toml, dotted_mod, scopes in checkout.path_scopes:
        files = set(table.module_files(dotted_mod, tops)) | {source_toml}
        first = dotted_mod.split(".", 1)[0]
        if first in tops and table.kind(dotted_mod) is None:
            missing.append((source_toml, dotted_mod))
        for scope in scopes:
            prefix = f"{scope}/"
            for test in checkout.collectable:
                if test == scope or test.startswith(prefix):
                    edges[test].update(files)
    return edges, tuple(missing)


def tree_scan_pins(
    collectable: frozenset[str],
    facts_by_file: Mapping[str, FileTestFacts] | None = None,
    pins: frozenset[str] = frozenset(),
) -> frozenset[str]:
    lint_tests = {
        path
        for path in collectable
        if path.rpartition("/")[2].startswith("test_lint_") and path.endswith(".py")
    }
    registry_tests: set[str] = (
        {
            path
            for path in collectable
            if (f := facts_by_file.get(path)) is not None and "registry" in f.markers
        }
        if facts_by_file is not None
        else set()
    )
    return frozenset((lint_tests | registry_tests | pins) & collectable)


def _ancestor_paths(path: str) -> list[str]:
    out = [path]
    curr = path.rpartition("/")[0]
    while curr:
        out.append(curr)
        curr = curr.rpartition("/")[0]
    out.append("")
    return out


def _runtime_consumers_for_path(path: str, reverse: Mapping[str, set[str]]) -> set[str]:
    found: set[str] = set()
    for anc in _ancestor_paths(path):
        found.update(reverse.get(anc, ()))
    return found


# meiva:note
# A Markdown file no test reads as code: one at the root, one under a declared documentation root, or
# one inside a `docs` directory, unless a test directory or an excluded root holds it or its name is
# one a repository's tooling reads (`[test-graph] doc-excluded-names`).
def _is_doc_only_path(path: str, graph: TestGraphPolicy) -> bool:
    if not path.endswith(".md"):
        return False
    parts = path.split("/")
    if "tests" in parts or parts[0] in graph.doc_excluded_roots:
        return False
    if len(parts) == 1 or parts[0] in graph.doc_dirs:
        return True
    return parts[-1] not in graph.doc_excluded_names and "docs" in parts[:-1]


def _is_frontend_only_path(path: str, graph: TestGraphPolicy) -> bool:
    return (
        path.startswith(graph.frontend_prefixes)
        and not path.endswith((".py", ".toml"))
        and not _is_doc_only_path(path, graph)
    )


def _is_global_path(path: str, checkout: TestCheckout) -> bool:
    graph = checkout.graph
    if path in _GLOBAL_NAMES or path in graph.global_files or path in checkout.global_files:
        return True
    return path.startswith(graph.global_prefixes)


def _build_runtime_edges(
    checkout: TestCheckout,
    facts_by_file: Mapping[str, FileTestFacts],
) -> tuple[dict[str, set[str]], tuple[tuple[str, str], ...]] | TestSelection:
    table = ModuleTable.build(checkout.python_files, checkout.top_packages)
    edges, missing_scopes = fixture_dependency_edges(checkout, table)
    for rel, facts in facts_by_file.items():
        if rel in checkout.global_files:
            continue
        if facts.flags & FACT_SYNTAX_ERROR:
            return TestSelection(
                "FULL",
                f"syntax-error:{rel}",
                tuple(sorted(checkout.collectable)),
                (f"head:{rel}:1: syntax error",),
            )
        deps = edges.setdefault(rel, set())
        deps.update(dep for dep in facts.imports if dep not in checkout.global_files)
        deps.update(facts.resources)
    return edges, missing_scopes


def _collect_tainted_and_diagnostics(
    reverse: Mapping[str, set[str]],
    facts_by_file: Mapping[str, FileTestFacts],
    missing_scopes: tuple[tuple[str, str], ...],
) -> tuple[set[str], list[str]]:
    diagnostics: list[str] = [
        f"head:{src}:0: missing declared fixture module: {mod}" for src, mod in missing_scopes
    ]
    tainted: set[str] = set()
    for dep_path, consumers in reverse.items():
        f_item = facts_by_file.get(dep_path)
        if consumers and f_item is not None and f_item.unknown_sites:
            tainted.update(consumers)
            diagnostics.extend(
                f"head:{dep_path}:{lineno}: {reason}: {expr}"
                for lineno, reason, expr in f_item.unknown_sites
            )
    for src, _mod in missing_scopes:
        tainted.update(reverse.get(src, ()))
    return tainted, diagnostics


def _select_for_one_path(
    path: str,
    checkout: TestCheckout,
    reverse: Mapping[str, set[str]],
) -> set[str]:
    runtime_hits = _runtime_consumers_for_path(path, reverse)
    if path.endswith("/conftest.py"):
        prefix = f"{path.rpartition('/')[0]}/"
        return {t for t in checkout.collectable if t.startswith(prefix)} | runtime_hits
    if path in checkout.collectable:
        return {path} | runtime_hits
    local_hits = package_local_tests(path, checkout.test_dirs, checkout.collectable)
    owner_hits = local_hits or package_local_tests(
        path, checkout.test_dirs, checkout.collectable, include_root_tests=True
    )
    return runtime_hits | owner_hits


def _first_global_changed(cleaned: tuple[str, ...], checkout: TestCheckout) -> str | None:
    for path in cleaned:
        if not path.startswith(checkout.graph.excluded_prefixes) and _is_global_path(
            path, checkout
        ):
            return path
    return None


def _accumulate_selected_tests(
    cleaned: tuple[str, ...],
    checkout: TestCheckout,
    reverse: Mapping[str, set[str]],
    *,
    base_available: bool,
    diagnostics: list[str],
) -> set[str] | TestSelection:
    selected: set[str] = set()
    for path in cleaned:
        if path.startswith(checkout.graph.excluded_prefixes) or _is_frontend_only_path(
            path, checkout.graph
        ):
            continue
        if path not in checkout.all_files and not base_available:
            return TestSelection(
                "FULL",
                "incomplete-impact",
                tuple(sorted(checkout.collectable)),
                (
                    *sorted(set(diagnostics)),
                    f"head:{path}: deleted path requires --base-ref to recover runtime impact",
                ),
            )
        selected.update(_select_for_one_path(path, checkout, reverse))
    return selected


# meiva:note
# Computes impacted collectable tests for `changed_paths`, failing closed to `"FULL"` on global
# config edits, syntax errors, deleted paths without `--base-ref`, or opaque dynamic imports.
def select_impacted_tests(
    changed_paths: tuple[str, ...],
    checkout: TestCheckout,
    facts_by_file: Mapping[str, FileTestFacts],
    *,
    base_available: bool = False,
) -> TestSelection:
    cleaned = tuple(dict.fromkeys(p.strip("/") for p in changed_paths if p.strip("/")))
    if not cleaned:
        return TestSelection("SKIP", "no-changed-files", (), ())
    if (global_hit := _first_global_changed(cleaned, checkout)) is not None:
        return TestSelection(
            "FULL", f"global-path:{global_hit}", tuple(sorted(checkout.collectable)), ()
        )

    built = _build_runtime_edges(checkout, facts_by_file)
    if isinstance(built, TestSelection):
        return built
    edges, missing_scopes = built
    reverse = propagate_test_consumers(edges, checkout.collectable)
    tainted, diagnostics = _collect_tainted_and_diagnostics(reverse, facts_by_file, missing_scopes)

    graph = checkout.graph
    if all(_is_frontend_only_path(p, graph) for p in cleaned):
        return TestSelection("SKIP", "frontend-only", (), ())
    if all(
        _is_doc_only_path(p, graph) and not _runtime_consumers_for_path(p, reverse) for p in cleaned
    ):
        return TestSelection("SKIP", "docs-only", (), ())

    accumulated = _accumulate_selected_tests(
        cleaned, checkout, reverse, base_available=base_available, diagnostics=diagnostics
    )
    if isinstance(accumulated, TestSelection):
        return accumulated

    final_tests = tuple(
        sorted(
            (
                accumulated
                | tainted
                | tree_scan_pins(checkout.collectable, facts_by_file, graph.tree_scan_pins)
            )
            & checkout.collectable
        )
    )
    return TestSelection(
        decision="SELECTED",
        reason="owner-tests",
        tests=final_tests,
        diagnostics=tuple(sorted(set(diagnostics))),
    )
