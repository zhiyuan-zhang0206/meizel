"""The language frontends and the records they hand the checker."""

from __future__ import annotations

from meizel.language.closure import reverse_closure
from meizel.language.file_scan import FileScan
from meizel.language.frontend import Frontend, RunView, StateKinds
from meizel.language.frontends import (
    DOOR_FILES,
    DYNAMIC_ATTR_FORMS,
    EXTERNAL_FORMS,
    FRONTENDS,
    PACKAGE_INITS,
    SOURCE_EXTENSIONS,
    enabled_frontends,
    frontend_of,
    invalidate_policy_caches,
    is_private_module,
    scan_all,
    scan_source,
)
from meizel.language.sources import (
    ambient_sources,
    candidates_of,
    projects,
    source_candidates,
    stale_readers,
)

__all__ = [
    "DOOR_FILES",
    "DYNAMIC_ATTR_FORMS",
    "EXTERNAL_FORMS",
    "FRONTENDS",
    "PACKAGE_INITS",
    "SOURCE_EXTENSIONS",
    "FileScan",
    "Frontend",
    "RunView",
    "StateKinds",
    "ambient_sources",
    "candidates_of",
    "enabled_frontends",
    "frontend_of",
    "invalidate_policy_caches",
    "is_private_module",
    "projects",
    "reverse_closure",
    "scan_all",
    "scan_source",
    "source_candidates",
    "stale_readers",
]
