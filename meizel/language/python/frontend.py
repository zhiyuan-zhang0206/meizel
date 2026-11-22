"""The Python frontend: the standard library's `ast`, in process."""

from __future__ import annotations

import re
from collections.abc import Sequence

from meizel.allowances import Policy
from meizel.graph.model import Code, Sources
from meizel.graph.universe import Universe
from meizel.language.file_scan import FileScan
from meizel.language.frontend import Frontend
from meizel.language.python.cache import scan_python_cached
from meizel.language.python.comments import scan_python_comments
from meizel.language.python.judge import (
    python_companions,
    python_evidence,
    python_facts,
    python_rules,
    python_sources,
    python_world_reads,
    stale_readers,
)
from meizel.language.python.resolve import python_modules, python_reverse_closure
from meizel.language.python.restricted import DYNAMIC_ATTR_FORMS, EXTERNAL_FORMS
from meizel.language.python.scanner import scan_source
from meizel.language.python.surface import python_item_reads

__all__ = ["PYTHON"]


def _owns(path: str, _policy: Policy) -> bool:
    return path.endswith(".py")


def _candidates(universe: Universe) -> Sequence[str]:
    return universe.files_ending((".py",))


def _files(universe: Universe, _policy: Policy) -> Sequence[str]:
    return _candidates(universe)


def _impacted(
    universe: Universe, changed: Sequence[str], jobs: int | None
) -> frozenset[str] | None:
    return python_reverse_closure(universe, changed, jobs=jobs)


def _projects(universe: Universe) -> tuple[str, ...]:
    return tuple(project.directory for project in python_modules(universe).standalone_projects)


def _scan_source(
    universe: Universe, path: str, source: bytes, sources: Sources, policy: Policy
) -> FileScan:
    return scan_source(universe, path, source, sources, policy=policy)


def _restricted_hint(_form: str, manifest: str) -> str:
    return (
        "use a static import, and inject a collaborator instead of patching it; a file that genuinely "
        f"owns a dynamic load declares it under [loads] in {manifest}; "
        "a file that runs code from outside the repository declares it under [external] with a reason; "
        "a file that owns an attribute name only the run knows declares it under [dynamic-attrs] with a reason"
    )


_PROTOCOL = re.compile(r"__\w+__(\.py)?")


def _protocol_name(child: str) -> bool:
    return _PROTOCOL.fullmatch(child) is not None


def _reads_scope(_policy: Policy) -> str:
    return "Python"


def _scope_advice(_where: str) -> str | None:
    return None


PYTHON = Frontend(
    "python",
    frozenset({"__init__.py"}),
    frozenset({"__init__.py"}),
    (".py",),
    _protocol_name,
    "python_ast",
    "Python files (stdlib AST)",
    _reads_scope,
    _scope_advice,
    _owns,
    _candidates,
    _files,
    scan_python_cached,
    python_sources,
    stale_readers,
    _scan_source,
    EXTERNAL_FORMS,
    DYNAMIC_ATTR_FORMS,
    python_facts,
    python_rules,
    python_companions,
    python_evidence,
    _impacted,
    _projects,
    python_world_reads,
    python_item_reads,
    Code.RESTRICTED,
    "Python",
    _restricted_hint,
    _candidates,
    scan_python_comments,
)
