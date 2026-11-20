# Which of a composition root's kinds licenses one purity item: the join between a `[roots]`
# declaration and the call the purity layer charged.
#
# A call is licensed in one of three ways. On its line: the scan records an acquisition of a
# licensed kind on the line the purity rule recorded the call on, which is the same call in
# whatever language judged it. By its name: the ambient table judges the recorded call a reader of a
# licensed kind, and the call is unconditional -- one with an `unless` clause reads nothing once it
# is handed the value. By the filesystem: a read of a file derives no acquisition (the purity
# layer charges it `impure-call`, see `AmbientKind`), so the kind licenses the call by its name,
# and the language says which calls those are (`ItemReads`).

from __future__ import annotations

from collections.abc import Iterable

from meizel.graph.model import Acquisition, ItemReads, KindName, PurityItem

__all__ = ["licensed"]


# The answer is the kinds that license the item, empty when the declaration does not reach it: the kinds
# of an acquisition on the item's own line, and a site-keyed item licenses by that alone; otherwise the
# kinds its language reads it by name as (`reads`).
def licensed(
    kinds: frozenset[KindName],
    acquisitions: Iterable[Acquisition],
    item: PurityItem,
    reads: ItemReads,
) -> frozenset[KindName]:
    on_line = frozenset(
        acquisition.kind
        for acquisition in acquisitions
        if acquisition.line == item.line and acquisition.kind in kinds
    )
    if on_line or "#" in item.key:
        return on_line
    return reads.named & kinds
