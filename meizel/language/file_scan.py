"""The record one scanned file becomes: what a frontend hands the checker, whatever the language."""

from __future__ import annotations

from dataclasses import dataclass, field

from meizel.graph.model import (
    Acquisition,
    AnyCollaboratorSite,
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

__all__ = ["FileScan", "read_source"]


@dataclass(frozen=True, slots=True)
class FileScan:
    path: str
    facts: list[Fact] = field(default_factory=list[Fact])
    restricted: list[Restricted] = field(default_factory=list[Restricted])
    patches: list[Patch] = field(default_factory=list[Patch])
    problems: list[Problem] = field(default_factory=list[Problem])
    purity: list[PurityItem] = field(default_factory=list[PurityItem])
    enum_subsets: list[EnumSubsetUse] = field(default_factory=list[EnumSubsetUse])
    ambient: list[Acquisition] = field(default_factory=list[Acquisition])
    type_casts: list[TypeCastSite] = field(default_factory=list[TypeCastSite])
    any_collaborators: list[AnyCollaboratorSite] = field(default_factory=list[AnyCollaboratorSite])
    symbols: tuple[tuple[str, int, int], ...] = ()
    injected: tuple[str, ...] = ()
    # What the frontend that read the file records of it besides these: its own type, which only
    # that frontend reads and encodes (`scan_codec` carries it as an opaque JSON object).
    extra: object = None


# The bytes of a tracked file, or the refusal that names the file when they cannot be read.
def read_source(universe: Universe, path: str) -> bytes:
    try:
        return universe.repo.load_bytes(path)
    except (OSError, ValueError) as error:
        raise MeizelError(f"{path}: cannot read: {error}") from error
