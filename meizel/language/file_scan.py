"""The record one scanned file becomes: what a frontend hands the checker, whatever the language."""

from __future__ import annotations

from dataclasses import dataclass, field

from meizel.graph.model import (
    Acquisition,
    AnyCollaboratorSite,
    EntropySite,
    EnumSubsetUse,
    Fact,
    MeizelError,
    Patch,
    Problem,
    PurityItem,
    Restricted,
    TypeCastSite,
)
from meizel.graph.universe import Universe
from meizel.language import fixtures

__all__ = ["FileScan", "InputListAppend", "read_source"]


@dataclass(frozen=True, slots=True)
class InputListAppend:
    line: int
    function: str
    parameter: str


@dataclass(frozen=True, slots=True)
class FileScan:
    path: str
    facts: list[Fact] = field(default_factory=list[Fact])
    restricted: list[Restricted] = field(default_factory=list[Restricted])
    patches: list[Patch] = field(default_factory=list[Patch])
    problems: list[Problem] = field(default_factory=list[Problem])
    fixtures: fixtures.FixtureState = field(default_factory=fixtures.FixtureState)
    imported: set[str] = field(default_factory=set[str])
    purity: list[PurityItem] = field(default_factory=list[PurityItem])
    enum_subsets: list[EnumSubsetUse] = field(default_factory=list[EnumSubsetUse])
    input_appends: list[InputListAppend] = field(default_factory=list[InputListAppend])
    ambient: list[Acquisition] = field(default_factory=list[Acquisition])
    entropy: list[EntropySite] = field(default_factory=list[EntropySite])
    type_casts: list[TypeCastSite] = field(default_factory=list[TypeCastSite])
    any_collaborators: list[AnyCollaboratorSite] = field(default_factory=list[AnyCollaboratorSite])
    type_checking: tuple[int, ...] = ()
    symbols: tuple[tuple[str, int, int], ...] = ()
    deps: tuple[str, ...] = ()
    injected: tuple[str, ...] = ()


# The bytes of a tracked file, or the refusal that names the file when they cannot be read.
def read_source(universe: Universe, path: str) -> bytes:
    try:
        return universe.repo.load_bytes(path)
    except (OSError, ValueError) as error:
        raise MeizelError(f"{path}: cannot read: {error}") from error
