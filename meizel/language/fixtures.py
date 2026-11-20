"""pytest fixture definitions and requests, and their resolution to a defining file."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from meizel.graph.model import Fact, FactKind
from meizel.graph.universe import Universe, parent_of

__all__ = [
    "DEFAULT_IMPURE_FIXTURES",
    "FixtureFunction",
    "FixtureIndex",
    "FixtureRequest",
    "FixtureState",
    "fixture_facts",
    "is_test_file",
]

DEFAULT_IMPURE_FIXTURES = frozenset({"monkeypatch"})


@dataclass(frozen=True, slots=True)
class FixtureRequest:
    name: str
    line: int
    skip_self: bool = False
    requester_line: int = 0
    form: Literal["parameter", "usefixtures", "call", "lookup"] = "parameter"


@dataclass(frozen=True, slots=True)
class FixtureFunction:
    name: str
    line: int
    registered: str | None
    module_owned: bool
    parameters_known: bool
    end_line: int = 0
    is_async: bool = False
    requests: tuple[str, ...] = ()
    imported_modules: tuple[str, ...] = ()
    callees: tuple[str, ...] = ()
    local_calls: tuple[str, ...] = ()
    names_loaded: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FixtureState:
    """Fixture facts of one file, gathered while it is scanned."""

    defs: set[str] = field(default_factory=set[str])
    requests: list[FixtureRequest] = field(default_factory=list[FixtureRequest])
    plugins: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])
    functions: list[FixtureFunction] = field(default_factory=list[FixtureFunction])
    helpers: list[FixtureFunction] = field(default_factory=list[FixtureFunction])


def is_test_file(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    if name.endswith((".ts", ".tsx", ".mts", ".cts")):
        return (
            name.endswith(
                (
                    ".test.ts",
                    ".test.tsx",
                    ".spec.ts",
                    ".spec.tsx",
                    "-test-mock.ts",
                    "-test-mock.tsx",
                    ".test.mts",
                    ".test.cts",
                    ".spec.mts",
                    ".spec.cts",
                    "-test-mock.mts",
                    "-test-mock.cts",
                )
            )
            or "tests" in parts[:-1]
            or "test-support" in parts[:-1]
        )
    return name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py")


@dataclass(frozen=True, slots=True)
class FixtureIndex:
    """What each scanned file defines, for resolving a request to its definer."""

    universe: Universe | None
    defined: dict[str, set[str]]
    plugins: dict[str, list[str]]
    _plugin_cache: dict[str, list[str]] = field(
        default_factory=dict[str, list[str]], init=False, repr=False, compare=False
    )

    def names(self, path: str) -> set[str]:
        return self.defined.get(path) or set()

    def plugin_files(self, path: str, seen: set[str] | None = None) -> list[str]:
        if self.universe is None:
            return []
        if seen is None and path in self._plugin_cache:
            return self._plugin_cache[path]
        top = seen is None
        active: set[str] = set() if seen is None else seen
        found: list[str] = []
        for dotted in self.plugins.get(path, ()):
            module = self.universe.resolve_module(dotted)
            if module is None or module.file is None or module.file in active:
                continue
            active.add(module.file)
            found.append(module.file)
            found.extend(self.plugin_files(module.file, active))
        if top:
            self._plugin_cache[path] = found
        return found

    def candidates(self, name: str, test_path: str) -> tuple[list[str], frozenset[str]]:
        visible = [test_path]
        directory = parent_of(test_path)
        while True:
            conftest = f"{directory}/conftest.py" if directory else "conftest.py"
            if conftest != test_path and conftest in self.defined:
                visible.append(conftest)
            if not directory:
                break
            directory = parent_of(directory)
        providers = [path for path in visible if name in self.names(path)]
        plugins = list(
            dict.fromkeys(
                plugin
                for path in visible
                for plugin in self.plugin_files(path)
                if plugin not in visible and name in self.names(plugin)
            )
        )
        return providers + plugins, frozenset(plugins) if len(plugins) > 1 else frozenset()

    def definer(self, request: FixtureRequest, src: str) -> str | None:
        """The file pytest takes `request` from; None when local or not first-party."""
        if not request.skip_self:
            if request.name in self.names(src):
                return None
            for plugin in self.plugin_files(src):
                if request.name in self.names(plugin):
                    return plugin
        directory = parent_of(src)
        if request.skip_self and src.endswith("conftest.py"):
            directory = parent_of(directory)
        return self._walk_up(request.name, directory, src)

    def _walk_up(self, name: str, directory: str, src: str) -> str | None:
        while True:
            conftest = f"{directory}/conftest.py" if directory else "conftest.py"
            if conftest in self.defined and conftest != src:
                if name in self.names(conftest):
                    return conftest
                for plugin in self.plugin_files(conftest):
                    if name in self.names(plugin):
                        return plugin
            if not directory:
                return None
            directory = parent_of(directory)


def fixture_facts(index: FixtureIndex, requests: dict[str, list[FixtureRequest]]) -> list[Fact]:
    facts: list[Fact] = []
    for src, items in requests.items():
        for request in items:
            target = index.definer(request, src)
            if target is not None and target != src:
                facts.append(
                    Fact(
                        src,
                        target,
                        request.line,
                        FactKind.FIXTURE,
                        (request.name,),
                        f"fixture {request.name}",
                    )
                )
    return facts
