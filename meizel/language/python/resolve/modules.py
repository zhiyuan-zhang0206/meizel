"""Python's view of a repository's modules: which dotted name is which file.

A name resolves to a file under a root directory of the tracked tree (or to the physical source an
independently packaged project's native name aliases). The view wraps a `Universe`, which knows
files and directories and nothing of modules, and is built once per universe (`python_modules`)."""

from __future__ import annotations

from dataclasses import dataclass

from meizel.graph.universe import MANIFEST, Universe
from meizel.language.python.resolve.layout import (
    StandaloneProject,
    project_metadata_paths,
    standalone_projects,
)

__all__ = ["Module", "PythonModules", "python_modules"]


@dataclass(frozen=True, slots=True)
class Module:
    """A first-party module: its source file, or None for a namespace directory."""

    file: str | None
    path: str


class PythonModules:
    """Module resolution over one universe, as one standalone project sees it (or none)."""

    def __init__(
        self,
        universe: Universe,
        projects: tuple[StandaloneProject, ...] = (),
        project: str | None = None,
        views: dict[str | None, PythonModules] | None = None,
    ) -> None:
        self.universe = universe
        self.repo = universe.repo
        self.root = universe.root
        self.files = universe.files
        self.dirs = universe.dirs
        self.children = universe.children
        self.python_files: tuple[str, ...] = universe.files_ending((".py",))
        self.standalone_projects = projects
        self._project = project
        active = next((item for item in projects if item.directory == project), None)
        self._python_aliases = dict(active.packages) if active is not None else {}
        self.roots: frozenset[str] = frozenset(
            name.removesuffix(".py") for name in self.children.get("", ())
        ) | frozenset(self._python_aliases)
        self._modules: dict[str, Module | None] = {}
        self._views: dict[str | None, PythonModules] = {project: self} if views is None else views

    def file_digests(self) -> dict[str, str]:
        return self.universe.file_digests()

    def context(self, origin: str) -> PythonModules:
        owner = next(
            (
                item.directory
                for item in self.standalone_projects
                if origin == item.directory or origin.startswith(item.directory + "/")
            ),
            None,
        )
        if owner not in self._views:
            self._views[owner] = PythonModules(
                self.universe, self.standalone_projects, owner, self._views
            )
        return self._views[owner]

    def context_for_module(self, dotted: str) -> PythonModules:
        head = dotted.split(".", 1)[0]
        for project in self.standalone_projects:
            if any(name == head for name, _ in project.packages):
                return self.context(project.directory)
        return self.context("")

    def canonical_name(self, dotted: str) -> str:
        head, separator, tail = dotted.partition(".")
        physical = self._python_aliases.get(head)
        return physical.replace("/", ".") + separator + tail if physical else dotted

    # Resolve root imports and explicit standalone wheel names to physical source.
    def resolve_module(self, dotted: str) -> Module | None:
        if dotted in self._modules:
            return self._modules[dotted]
        path = self.canonical_name(dotted).replace(".", "/")
        found: Module | None = None
        if f"{path}.py" in self.files:
            found = Module(f"{path}.py", f"{path}.py")
        elif f"{path}/__init__.py" in self.files:
            found = Module(f"{path}/__init__.py", path)
        elif path in self.dirs and path:
            found = Module(None, path)
        self._modules[dotted] = found
        return found

    def is_first_party_name(self, dotted: str) -> bool:
        return dotted.split(".", 1)[0] in self.roots


def _build(universe: Universe) -> PythonModules:
    root_manifest = universe.repo.load_text(MANIFEST) if MANIFEST in universe.files else ""
    names = project_metadata_paths(universe.files, root_manifest)
    texts = {name: universe.repo.load_text(name) for name in names}
    return PythonModules(universe, standalone_projects(universe.files, root_manifest, texts))


# The module view of `universe`, built on first use: the metadata of independently packaged projects is
# read then, so a repository that does not read Python never reads it.
def python_modules(universe: Universe) -> PythonModules:
    view = universe.memo("python-modules", lambda: _build(universe))
    return view if isinstance(view, PythonModules) else _build(universe)
