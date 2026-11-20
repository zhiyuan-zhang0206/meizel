"""What Python's standard library reads of the world, name by name: the table of judgments, the
clocks and generators the rules know, and the calls a root licenses by their name."""

from __future__ import annotations

from meizel.language.python.surface.reads import FILESYSTEM_READS, SLEEP_CALLS, python_item_reads
from meizel.language.python.surface.surface import (
    INTERVAL_CLOCKS,
    LOOP_CLOCK,
    METHOD_READS,
    SEEDABLE_GENERATORS,
    judged,
    unjudged,
)

__all__ = [
    "FILESYSTEM_READS",
    "INTERVAL_CLOCKS",
    "LOOP_CLOCK",
    "METHOD_READS",
    "SEEDABLE_GENERATORS",
    "SLEEP_CALLS",
    "judged",
    "python_item_reads",
    "unjudged",
]
