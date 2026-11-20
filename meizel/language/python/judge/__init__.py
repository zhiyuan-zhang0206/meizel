"""What the Python frontend judges over a run: the rules, the facts, the evidence and the readers, beyond what one file's scan decides."""

from __future__ import annotations

from meizel.language.python.judge.explain import python_evidence
from meizel.language.python.judge.pytest_scope import python_companions, python_facts
from meizel.language.python.judge.readers import python_sources, stale_readers
from meizel.language.python.judge.rules import (
    python_rules,
    type_checking_in_scope,
    type_checking_lines,
    type_checking_violations,
)
from meizel.language.python.judge.world_reads import python_world_reads

__all__ = [
    "python_companions",
    "python_evidence",
    "python_facts",
    "python_rules",
    "python_sources",
    "python_world_reads",
    "stale_readers",
    "type_checking_in_scope",
    "type_checking_lines",
    "type_checking_violations",
]
