"""The Python frontend: the standard library's `ast`, in process."""

from __future__ import annotations

from collections.abc import Sequence

from meizel.allowances import Policy
from meizel.graph.model import Code, Sources
from meizel.graph.universe import Universe
from meizel.language.file_scan import FileScan
from meizel.language.frontend import Frontend
from meizel.language.python.cache import scan_python_cached
from meizel.language.python.restricted import DYNAMIC_ATTR_FORMS, EXTERNAL_FORMS
from meizel.language.python.scanner import scan_source

__all__ = ["PYTHON"]


def _owns(path: str, _policy: Policy) -> bool:
    return path.endswith(".py")


def _files(universe: Universe, _policy: Policy) -> Sequence[str]:
    return universe.python_files


def _scan_source(
    universe: Universe, path: str, source: bytes, sources: Sources, policy: Policy
) -> FileScan:
    return scan_source(universe, path, source, sources, policy=policy)


PYTHON = Frontend(
    "python",
    _owns,
    _files,
    scan_python_cached,
    _scan_source,
    EXTERNAL_FORMS,
    DYNAMIC_ATTR_FORMS,
    Code.RESTRICTED,
    "Python",
    "use a static import, and inject a collaborator instead of patching it",
)
