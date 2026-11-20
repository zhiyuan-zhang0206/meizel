"""What pytest collects around the Python files a run reads: the fixtures a test resolves to a
`conftest.py` or a plugin, the plugins a `path_scopes.toml` mounts, and the files a partial run must
read for those resolutions to be the whole run's."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from meizel.graph.model import Diagnostic, Fact
from meizel.graph.universe import Universe, parent_of
from meizel.language.file_scan import FileScan
from meizel.language.frontend import RunView
from meizel.language.python.fixtures import FixtureIndex, fixture_facts
from meizel.language.python.mounts import mount_facts
from meizel.language.python.record import python_record

__all__ = ["python_companions", "python_facts"]


def _fixture_facts(view: RunView, universe: Universe) -> list[Fact]:
    records = {path: python_record(scan) for path, scan in view.scans.items()}
    defined = {
        path: record.fixtures.defs | record.imported
        for path, record in records.items()
        if record.fixtures.defs or path.endswith("conftest.py") or record.fixtures.plugins
    }
    plugins = {
        path: [name for name, _ in record.fixtures.plugins]
        for path, record in records.items()
        if record.fixtures.plugins
    }
    judged = {scan.path for scan in view.judged}
    requests = {
        path: record.fixtures.requests
        for path, record in records.items()
        if record.fixtures.requests and path in judged
    }
    return fixture_facts(FixtureIndex(universe, defined, plugins), requests)


# The fixture fact of every judged request, and the plugin of every mount of a `path_scopes.toml`.
def python_facts(view: RunView) -> tuple[list[Fact], list[Diagnostic]]:
    universe = view.universe
    if universe is None:
        return [], []
    mounts, unmounted = mount_facts(universe, view.changed)
    return [*_fixture_facts(view, universe), *mounts], unmounted


def _ancestor_conftests(universe: Universe, path: str) -> list[str]:
    found: list[str] = []
    directory = parent_of(path)
    while True:
        candidate = f"{directory}/conftest.py" if directory else "conftest.py"
        if candidate in universe.files:
            found.append(candidate)
        if not directory:
            return found
        directory = parent_of(directory)


def _needed_conftests(universe: Universe, scans: Mapping[str, FileScan]) -> list[str]:
    needed: set[str] = set()
    for scan in scans.values():
        fixtures = python_record(scan).fixtures
        if fixtures.requests or fixtures.plugins:
            needed.update(_ancestor_conftests(universe, scan.path))
    return sorted(needed - scans.keys())


def _missing_plugins(universe: Universe, scans: Mapping[str, FileScan]) -> list[str]:
    found: set[str] = set()
    for scan in scans.values():
        for name, _ in python_record(scan).fixtures.plugins:
            mod = universe.resolve_module(name)
            if mod is not None and mod.file is not None and mod.file not in scans:
                found.add(mod.file)
    return sorted(found)


# The ancestor `conftest.py` files of the scans that request fixtures or declare plugins, and then the
# modules those plugins name, each round read through `scan_more` until nothing is missing.
def python_companions(
    universe: Universe,
    scans: Mapping[str, FileScan],
    scan_more: Callable[[list[str]], dict[str, FileScan]],
) -> dict[str, FileScan]:
    known = dict(scans)
    added: dict[str, FileScan] = {}
    conftests = _needed_conftests(universe, known)
    if conftests:
        added.update(scan_more(conftests))
        known.update(added)
    while more := _missing_plugins(universe, known):
        found = scan_more(more)
        added.update(found)
        known.update(found)
    return added
