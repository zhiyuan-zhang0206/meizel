"""The language frontends and the records they hand the checker."""

from __future__ import annotations

from meizel.language.file_scan import FileScan, InputListAppend
from meizel.language.frontend import Frontend
from meizel.language.frontends import (
    DYNAMIC_ATTR_FORMS,
    EXTERNAL_FORMS,
    FRONTENDS,
    enabled_frontends,
    frontend_of,
    invalidate_policy_caches,
    scan_all,
    scan_source,
)

__all__ = [
    "DYNAMIC_ATTR_FORMS",
    "EXTERNAL_FORMS",
    "FRONTENDS",
    "FileScan",
    "Frontend",
    "InputListAppend",
    "enabled_frontends",
    "frontend_of",
    "invalidate_policy_caches",
    "scan_all",
    "scan_source",
]
