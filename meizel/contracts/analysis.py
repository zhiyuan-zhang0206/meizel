"""Whole-repository analysis: facts, projections and every diagnostic."""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field

from meizel.contracts.ambient_read import (
    ambient_diagnostics,
    in_scope,
    reader_problems,
    sources_from,
    stale_roots,
)
from meizel.contracts.debt import (
    PATCH_HINT,
    PATCH_REASONING,
    PATCH_WHAT,
    PURITY_CODES,
    DebtEntry,
    entry_value,
    file_key,
    read_entry,
    set_debt,
)
from meizel.contracts.enumerations import check as check_roles
from meizel.contracts.ledger import account_line, legal_read_recorded, reconcile
from meizel.contracts.manifest import Manifest, effective_purity, load_manifests, manifest_path
from meizel.contracts.policy import POLICY, Policy, load_policy, render_policy
from meizel.contracts.policy import check as check_policy
from meizel.contracts.purity_mode import purity_debt, test_purity_mode
from meizel.contracts.rule import (
    Projection,
    judge_facts,
    paid_strict_to_be,
    purity_diagnostics,
    stale_exports,
)
from meizel.graph import python_reverse_closure
from meizel.graph.model import Code, DebtKey, Diagnostic, Fact, FactKind, Patch, Sources
from meizel.graph.universe import Universe
from meizel.language import (
    DYNAMIC_ATTR_FORMS,
    EXTERNAL_FORMS,
    FileScan,
    RunView,
    enabled_frontends,
    frontend_of,
    scan_all,
    stale_readers,
)
from meizel.language.test_files import is_test_file
from meizel.language.typescript import typescript_scopes
from meizel.lint_common import is_test_path

_EMPTY_POLICY = Policy()
_PRUNE = "run `python -m meizel sync --prune` to remove it"

__all__ = [
    "POLICY",
    "Analysis",
    "DebtEntry",
    "Policy",
    "analyze",
    "diagnose",
    "entry_value",
    "exempt_test_modules",
    "load_manifests",
    "load_policy",
    "manifest_diagnostics",
    "python_reverse_closure",
    "read_entry",
    "render_policy",
    "scan_all",
    "set_debt",
]


@dataclass(frozen=True, slots=True)
class Analysis:
    """Everything one run found.

    `diagnostics` holds every violation the rules found. `verdict` holds the ones that fail
    `check` once each directory's recorded debt is taken into account. `changed` is the set of
    files a `check --changed` run judged, or None for a whole-repository run.
    """

    universe: Universe
    manifests: dict[str, Manifest]
    scans: dict[str, FileScan]
    facts: list[Fact]
    projections: list[Projection]
    diagnostics: list[Diagnostic] = field(default_factory=list[Diagnostic])
    verdict: list[Diagnostic] = field(default_factory=list[Diagnostic])
    changed: frozenset[str] | None = None
    needed: dict[tuple[str, str, str], list[Fact]] = field(
        default_factory=dict[tuple[str, str, str], list[Fact]]
    )
    stale_edges: list[tuple[str, str, str]] = field(default_factory=list[tuple[str, str, str]])
    stale_loads: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    stale_externals: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    stale_exports: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    # Warnings the run cannot turn into a violation: (manifest, the line to print).
    inert: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    stale_dynamic_attrs: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    def language_counts(self) -> dict[str, int]:
        return {
            "python_ast": sum(path.endswith(".py") for path in self.scans),
            "typescript_compiler_ast": sum(not path.endswith(".py") for path in self.scans),
        }

    def coverage_line(self) -> str:
        counts = self.language_counts()
        return (
            f"meizel: analyzed {counts['python_ast']} Python files (stdlib AST), "
            f"{counts['typescript_compiler_ast']} TypeScript files (compiler AST); "
            "selection and rule coverage follow repository policy"
        )

    def ok_line(self) -> str:
        scope = "" if self.changed is None else f"{len(self.changed)} changed paths, "
        return (
            f"meizel: ok ({scope}{len(self.facts)} fact edges, "
            f"{len(self.manifests)} manifests{account_line(self.manifests, self.scans)}); "
            "implemented checks passed for the reported scope; "
            "not a semantic purity proof or test-resource assessment"
        )


def _all_source_files(universe: Universe, policy: Policy) -> tuple[str, ...]:
    return tuple(
        path for frontend in enabled_frontends(policy) for path in frontend.files(universe, policy)
    )


def _load_facts(manifests: dict[str, Manifest]) -> list[Fact]:
    facts: list[Fact] = []
    for directory, manifest in manifests.items():
        for name, targets in manifest.loads.items():
            src = f"{directory}/{name}" if directory else name
            facts.extend(
                Fact(src, target, manifest.line_of(name), FactKind.LOAD, (), f"[loads] {target}")
                for target in targets
            )
    return facts


# The `[loads]`, `[external]` and `[dynamic-attrs]` files, as repository paths.
def _declared_sites(manifests: dict[str, Manifest]) -> tuple[set[str], set[str], set[str]]:
    def paths(table: Callable[[Manifest], Iterable[str]]) -> set[str]:
        return {
            f"{directory}/{name}" if directory else name
            for directory, manifest in manifests.items()
            for name in table(manifest)
        }

    return paths(lambda m: m.loads), paths(lambda m: m.external), paths(lambda m: m.dynamic_attrs)


def _source_diagnostics(
    scans: Iterable[FileScan],
    loaders: set[str],
    externals: set[str],
    owners: set[str],
    policy: Policy,
) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    for scan in scans:
        found.extend(Diagnostic(scan.path, p.line, p.code, p.message) for p in scan.problems)
        if scan.path in loaders:
            continue
        owner = scan.path.rpartition("/")[0]
        frontend = frontend_of(scan.path, policy)
        for item in scan.restricted:
            if scan.path in externals and item.form in EXTERNAL_FORMS:
                continue
            if scan.path in owners and item.form in DYNAMIC_ATTR_FORMS:
                continue
            form = f"{item.form}{' ' + repr(item.detail) if item.detail else ''}"
            found.append(
                Diagnostic(
                    scan.path,
                    item.line,
                    frontend.restricted_code,
                    f"{form} is outside the restricted {frontend.restricted_subset} subset",
                    (frontend.restricted_hint(item.form, manifest_path(owner)),),
                    DebtKey(owner, file_key(owner, scan.path, form)),
                )
            )
    return found


_TEST_MODULE = re.compile(r"^test_|_test\.py$|\.(?:test|spec)\.")


# `[approved-patches.files]`: the files that are allowed to patch, each with the reason. A patch is
# debt: the code under test should take its collaborator instead. A few test-support files patch on
# purpose, because their job is to keep the suite off the host or to put a child process in a state no
# parameter can reach: an autouse guard, the entry of a subprocess the test starts, the global setup of
# the test runner. The policy lists such a file by its path; none of its patches is then judged. Only
# fixture infrastructure qualifies: production code and test modules never do, so a test that patches
# is converted, not approved.
def _approved(policy: Policy) -> dict[str, str]:
    return policy.reasons("approved-patches", "files")


def _approval_refusal(path: str) -> str | None:
    if not is_test_path(path):
        return "is production code: approving a patch there would hide a dependency that should be injected"
    if _TEST_MODULE.search(path.rpartition("/")[2]):
        return "is a test module: a test that patches is converted, not approved"
    return None


# An entry that cannot be approved (production code, a test module), whether the run is partial or whole.
def _approval_problems(policy: Policy) -> list[Diagnostic]:
    refused = {path: _approval_refusal(path) for path in _approved(policy)}
    return [
        Diagnostic(
            POLICY,
            policy.line_of(path, "approved-patches.files"),
            Code.POLICY_SYNTAX,
            f"[approved-patches.files] {path!r} {refusal}",
            ("approve only fixture infrastructure: a guard, a subprocess entry, a global setup",),
        )
        for path, refusal in refused.items()
        if refusal is not None
    ]


# An approval that approves nothing fails like any other stale allowance: the file is gone, or it
# patches nothing any more. Only a whole-repository run knows.
def _stale_approvals(
    policy: Policy, files: Collection[str], patching: Mapping[str, int]
) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    for path in _approved(policy):
        if path not in files:
            problem = "names no tracked file"
        elif not patching.get(path):
            problem = "patches nothing any more"
        else:
            continue
        found.append(
            Diagnostic(
                POLICY,
                policy.line_of(path, "approved-patches.files"),
                Code.STALE_APPROVAL,
                f"[approved-patches.files] {path!r} {problem}",
                ("remove the entry",),
            )
        )
    return found


# The modules the run's facts show as test code that nothing outside the tests imports, each named
# the way a patch target names it: a TypeScript file by its path, a Python module by its dotted name
# (`meizel/tests/codes/test_x.py` is `meizel.tests.codes.test_x`). An importer the run did not scan cannot
# clear the exemption: the answer is as complete as the run's fact graph. Public because the check's own
# test states this set and the production import that empties one entry.
def exempt_test_modules(facts: Iterable[Fact]) -> frozenset[str]:
    reached = [fact for fact in facts if fact.kind in (FactKind.IMPORT, FactKind.PATCH)]
    shipped = {fact.dst for fact in reached if not is_test_file(fact.src)}
    return frozenset(
        _target_name(fact.dst)
        for fact in reached
        if is_test_file(fact.dst) and fact.dst not in shipped
    )


# Whether a target names one of these modules or a name bound inside one: a target adds the patched
# name to the module it reaches (`page-test-mock.tsx.activeId`, `lib.mod.helper`).
def _names_test_code(target: str, modules: Collection[str]) -> bool:
    candidate = target
    while candidate:
        if candidate in modules:
            return True
        candidate, separator, _ = candidate.rpartition(".")
        if not separator:
            return False
    return False


# The module part of a patch target that names `path`: a TypeScript file keeps its path, a Python module
# is written dotted (`meizel/tests/codes/test_x.py` is `meizel.tests.codes.test_x`).
def _target_name(path: str) -> str:
    if not path.endswith(".py"):
        return path
    return path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")


# How a patch reads: its form and the code's own word for what it targets.
def _patch_message(patch: Patch) -> str:
    if patch.code is Code.PATCH_RAISING_FALSE:
        return f"{patch.form}(..., raising=False) on {patch.target}"
    if patch.code is Code.TEST_SUBCLASS_OVERRIDE:
        return f"a test subclass overrides {patch.target}"
    suffix = " (imported binding)" if patch.imported else ""
    return f"{patch.form} on {PATCH_WHAT[patch.code]} {patch.target}{suffix}"


def _patch_hints(patch: Patch) -> tuple[str, ...]:
    hints = list(PATCH_REASONING.get(patch.code) or (PATCH_HINT[patch.code],))
    if patch.imported:
        hints.append(
            "target is an imported binding on this module rather than defined here; "
            "patch the defining module or inject the dependency"
        )
    return tuple(hints)


# Patching: the dependency was not injected. A file the policy approves is not judged, and neither is
# a patch of test code: a test that drives its own mock reaches no collaborator of the code under
# test.
def _patch_diagnostics(
    scans: Iterable[FileScan], approved: Collection[str], facts: Iterable[Fact]
) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    test_code = exempt_test_modules(facts)
    for scan in scans:
        if scan.path in approved:
            continue
        owner = scan.path.rpartition("/")[0]
        for patch in scan.patches:
            if patch.code is Code.FIRST_PARTY_PATCH and _names_test_code(patch.target, test_code):
                continue
            found.append(
                Diagnostic(
                    scan.path,
                    patch.line,
                    patch.code,
                    _patch_message(patch),
                    _patch_hints(patch),
                    DebtKey(owner, file_key(owner, scan.path, f"{patch.form} {patch.target}")),
                )
            )
    return found


# The declared sites whose file no longer has a restricted form of the kind the declaration exempts
# (`forms`, or any restricted form for a `[loads]` site), as (directory, name).
def _stale_sites(
    scans: dict[str, FileScan], declared: set[str], forms: frozenset[str] | None
) -> list[tuple[str, str]]:
    return sorted(
        (path.rpartition("/")[0], path.rpartition("/")[2])
        for path in declared
        if path not in scans
        or not any(forms is None or r.form in forms for r in scans[path].restricted)
    )


def _stale_edges(
    manifests: dict[str, Manifest], needed: dict[tuple[str, str, str], list[Fact]]
) -> list[tuple[str, str, str]]:
    return [
        (directory, cf, ct)
        for directory, manifest in sorted(manifests.items())
        for cf, targets in manifest.uses.items()
        for ct in targets
        if (directory, cf, ct) not in needed
    ]


@dataclass(frozen=True, slots=True)
class StaleDeclarations:
    """Declared edges, loads and externals that nothing needs; only a whole run knows them."""

    edges: list[tuple[str, str, str]] = field(default_factory=list[tuple[str, str, str]])
    loads: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    externals: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    exports: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    dynamic_attrs: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])


def _stale_diagnostics(
    manifests: dict[str, Manifest], stale: StaleDeclarations
) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    for directory, cf, ct in stale.edges:
        manifest = manifests[directory]
        found.append(
            Diagnostic(
                manifest.path,
                manifest.line_of(cf),
                Code.MANIFEST_STALE_EDGE,
                f"{cf} -> {ct} is declared but no fact edge needs it",
                (_PRUNE,),
            )
        )
    for sites, code, what, fix in (
        (
            stale.loads,
            Code.STALE_LOAD,
            "[loads] {!r} is declared but the file has no dynamic load",
            _PRUNE,
        ),
        (
            stale.externals,
            Code.STALE_EXTERNAL,
            "[external] {!r} is declared but the file runs no external code",
            "remove the entry",
        ),
        (
            stale.dynamic_attrs,
            Code.STALE_DYNAMIC_ATTRS,
            "[dynamic-attrs] {!r} is declared but the file has no dynamic attribute name",
            "remove the entry",
        ),
    ):
        for directory, name in sites:
            manifest = manifests[directory]
            found.append(
                Diagnostic(manifest.path, manifest.line_of(name), code, what.format(name), (fix,))
            )
    return found


# Scans only changed source files first, then what each frontend needs read alongside them: for the
# Python frontend the ancestor conftest.py files and transitive pytest_plugins modules of the tests
# that request fixtures or declare plugins.
def _scan_changed(
    universe: Universe, sources: Sources, changed: Collection[str], jobs: int | None, policy: Policy
) -> dict[str, FileScan]:
    initial = sorted(p for p in _all_source_files(universe, policy) if p in changed)
    scans = scan_all(universe, sources, jobs, initial, policy=policy)

    def scan_more(paths: list[str]) -> dict[str, FileScan]:
        return scan_all(universe, sources, jobs, paths, policy=policy)

    for frontend in enabled_frontends(policy):
        scans.update(frontend.companions(universe, scans, scan_more))
    return scans


def _distinct(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """One diagnostic per site and message, as `check` prints them."""
    return list({(d.path, d.line, d.code, d.message): d for d in diagnostics}.values())


def _type_cast_diagnostics(scans: Iterable[FileScan]) -> list[Diagnostic]:
    return [
        Diagnostic(
            scan.path,
            site.line,
            Code.TYPE_CAST,
            f"{'typing.cast call' if scan.path.endswith('.py') else 'TypeScript type assertion'} in {site.qualname} at byte column {site.column}",
            (
                "why: a type assertion does not validate the value",
                "instead: validate or narrow the value at its boundary",
                "see: meizel/docs/checker/type-cast.md",
            ),
            DebtKey(
                scan.path.rpartition("/")[0],
                file_key(scan.path.rpartition("/")[0], scan.path, f"cast {site.qualname}"),
            ),
        )
        for scan in scans
        for site in scan.type_casts
    ]


def _any_collaborator_diagnostics(scans: Iterable[FileScan]) -> list[Diagnostic]:
    return [
        Diagnostic(
            scan.path,
            site.line,
            Code.ANY_COLLABORATOR,
            f"{'typing.Any' if scan.path.endswith('.py') else 'any'} {site.role} annotation on {site.qualname}.{site.slot} at byte column {site.column}",
            (
                "why: an unrestricted Any type disables checking across collaborator boundaries",
                "instead: use a concrete collaborator type, a Protocol, or narrow object/Mapping values with TypeGuard/TypeIs or isinstance (do not use typing.cast, which [type-cast] forbids)",
                "see: meizel/docs/checker/any-collaborator.md",
            ),
            DebtKey(
                scan.path.rpartition("/")[0],
                file_key(
                    scan.path.rpartition("/")[0], scan.path, f"any {site.qualname}.{site.slot}"
                ),
            ),
        )
        for scan in scans
        for site in scan.any_collaborators
    ]


# What a frontend's rules are told of a run, with the answers the manifests give.
def _run_view(
    universe: Universe | None,
    policy: Policy,
    scans: Mapping[str, FileScan],
    judged: list[FileScan],
    changed: frozenset[str] | None,
    manifests: dict[str, Manifest],
) -> RunView:
    root = manifests.get("")
    return RunView(
        universe,
        policy,
        scans,
        judged,
        changed,
        {} if root is None else root.roles,
        lambda path: effective_purity(path, manifests),
        lambda scan: test_purity_mode(scan, manifests),
        lambda path: in_scope(path, manifests),
        lambda path, what, mode: purity_debt(path.rpartition("/")[0], path, what, mode),
    )


# The diagnostics a single file produces on its own, without whole-repository facts.
def diagnose(
    scan: FileScan,
    manifests: dict[str, Manifest],
    *,
    policy: Policy | None = None,
    universe: Universe | None = None,
) -> list[Diagnostic]:
    pol = _EMPTY_POLICY if policy is None else policy
    _, found, _ = judge_facts(scan.facts, manifests)
    loaders, externals, owners = _declared_sites(manifests)
    found.extend(_source_diagnostics([scan], loaders, externals, owners, pol))
    found.extend(_patch_diagnostics([scan], _approved(pol), scan.facts))
    found.extend(ambient_diagnostics([scan], manifests))
    found.extend(_type_cast_diagnostics([scan]) + _any_collaborator_diagnostics([scan]))
    found.extend(purity_diagnostics([scan], [scan], manifests, pol, include_manifests=False))
    view = _run_view(universe, pol, {scan.path: scan}, [scan], None, manifests)
    found.extend(frontend_of(scan.path, pol).rules(view))
    return _distinct(found)


# Analyse the repository, or with `changed` only the facts those files contribute.
#
# A partial run still reads every manifest, so the declared graphs are checked in full. It
# judges the changed files' fact edges, restricted forms and recorded debt, and every `[loads]`
# declaration, but not stale graph declarations: those need the whole repository's facts.
# Generated role lists and copies are checked globally in both modes, using this universe
# and the parsed root roles; they do not widen the fact scan.
# A `[roots]` table no rule can consult: an exemption is read when that file's own reads are judged,
# so a table in a directory this run never analyses exempts nothing while looking like a repaid read
# (a probe: adding it and deleting it left `check` byte-identical). It is a warning, never a
# violation: no rule forbids the table, the tool just cannot honour it.
def _inert_roots(
    manifests: Mapping[str, Manifest],
    *,
    analysed: Collection[str],
    tracked: Collection[str],
    scopes: tuple[str, ...],
) -> list[tuple[str, str]]:
    judged = frozenset(path.rpartition("/")[0] for path in analysed)
    source_dirs = {
        path.rpartition("/")[0] for path in tracked if path.rsplit("/", 1)[-1] != "meizel.toml"
    }
    covered = ", ".join(scopes) if scopes else "none declared"
    found: list[tuple[str, str]] = []
    for directory, manifest in sorted(manifests.items()):
        if not manifest.roots or directory in judged or directory not in source_dirs:
            continue
        names = ", ".join(f'"{name}"' for name in sorted(manifest.roots))
        line = min(manifest.line_of(name) for name in manifest.roots)
        where = directory or "the repository root"
        found.append(
            (
                manifest_path(directory),
                f"meizel: warning: {manifest_path(directory)}:{line}: [roots] {names} exempt "
                f"nothing: this run reads Python and the files inside [typescript].scopes "
                f"({covered}); no file directly in {where} is judged -- delete the entries, or "
                f"add {where} to the scopes so the TypeScript it names is read, unless a "
                f"`.d.ts` declaration is all it names, which no scope can make readable",
            )
        )
    return found


def _load_declarations(
    universe: Universe, scope: frozenset[str] | None
) -> tuple[dict[str, Manifest], Policy, list[Diagnostic]]:
    policy, policy_problems = load_policy(universe)
    manifests, diagnostics = load_manifests(universe, policy.state_kinds)
    diagnostics.extend(policy_problems)
    diagnostics.extend(check_policy(manifests, policy))
    diagnostics.extend(reader_problems(policy))
    diagnostics.extend(legal_read_recorded(manifests))
    diagnostics.extend(_approval_problems(policy))
    root_manifest = manifests.get("")
    diagnostics.extend(
        check_roles(universe, root_manifest.roles if root_manifest else {}, changed=scope)
    )
    return manifests, policy, diagnostics


def manifest_diagnostics(universe: Universe) -> list[Diagnostic]:
    return _distinct(_load_declarations(universe, None)[2])


def analyze(
    universe: Universe, *, jobs: int | None = None, changed: Collection[str] | None = None
) -> Analysis:
    scope = None if changed is None else frozenset(changed)
    manifests, policy, diagnostics = _load_declarations(universe, scope)
    sources = sources_from(manifests, policy, universe)
    scans = (
        scan_all(universe, sources, jobs, policy=policy)
        if scope is None
        else _scan_changed(universe, sources, scope, jobs, policy)
    )
    judged = sorted(scans if scope is None else scope & scans.keys())
    judged_scans = [scans[p] for p in judged]
    loaders, externals, owners = _declared_sites(manifests)
    facts = [f for scan in judged_scans for f in scan.facts]
    view = _run_view(universe, policy, scans, judged_scans, scope, manifests)
    facts.extend(_load_facts(manifests))
    for frontend in enabled_frontends(policy):
        added, unread = frontend.facts(view)
        facts.extend(added)
        diagnostics.extend(unread)
    projections, found, needed = judge_facts(facts, manifests)
    diagnostics.extend(found)
    diagnostics.extend(_source_diagnostics(judged_scans, loaders, externals, owners, policy))
    diagnostics.extend(_patch_diagnostics(judged_scans, _approved(policy), facts))
    diagnostics.extend(ambient_diagnostics(judged_scans, manifests))
    diagnostics.extend(_type_cast_diagnostics(judged_scans))
    diagnostics.extend(_any_collaborator_diagnostics(judged_scans))
    purity_diags = purity_diagnostics(scans.values(), judged_scans, manifests, policy)
    for frontend in enabled_frontends(policy):
        for ruled in frontend.rules(view):
            (purity_diags if ruled.code in PURITY_CODES else diagnostics).append(ruled)
    stale = StaleDeclarations()
    inert: list[tuple[str, str]] = []
    if scope is None:
        export_diags, unused_exports = stale_exports(manifests, projections)
        purity_diags.extend(export_diags)
        stale = StaleDeclarations(
            _stale_edges(manifests, needed),
            _stale_sites(scans, loaders, None),
            _stale_sites(scans, externals, EXTERNAL_FORMS),
            unused_exports,
            _stale_sites(scans, owners, DYNAMIC_ATTR_FORMS),
        )
        diagnostics.extend(_stale_diagnostics(manifests, stale))
        diagnostics.extend(stale_roots(scans, manifests))
        inert = _inert_roots(
            manifests,
            analysed=scans,
            tracked=universe.files,
            scopes=typescript_scopes(policy),
        )
        diagnostics.extend(stale_readers(universe, policy))
        diagnostics.extend(
            _stale_approvals(policy, universe.files, {p: len(s.patches) for p, s in scans.items()})
        )
        diagnostics.extend(paid_strict_to_be(manifests, purity_diags))
    diagnostics.extend(purity_diags)
    diagnostics = _distinct(diagnostics)
    return Analysis(
        universe,
        manifests,
        scans,
        facts,
        projections,
        diagnostics,
        reconcile(diagnostics, manifests, lambda path: scope is None or path in scope),
        scope,
        needed,
        stale.edges,
        stale.loads,
        stale.externals,
        stale.exports,
        inert,
        stale.dynamic_attrs,
    )
