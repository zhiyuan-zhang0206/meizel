"""The Python frontend. What the checker reads of it from outside: the frontend, the tables its
purity and ambient rules judge a Python file against, and the readings of a Python module that the
ambient rule asks for. The Python-specific code behind them stays in this package."""

from __future__ import annotations

from meizel.language.python.bindings import is_imported_binding, module_bindings
from meizel.language.python.cache import (
    cached_module_imports,
    load_cached_sources,
    store_cached_sources,
)
from meizel.language.python.frontend import PYTHON
from meizel.language.python.mounts import mount_facts
from meizel.language.python.purity import (
    ALLOWED_STDLIB_MODULES,
    DEFAULT_IMPURE_CALLS,
    IMPURE_DOTTED_STDLIB_MODULES,
    IMPURE_STDLIB_MODULES,
)
from meizel.language.python.scanner import TYPE_CHECKING_MESSAGE, scan_tree

__all__ = [
    "ALLOWED_STDLIB_MODULES",
    "DEFAULT_IMPURE_CALLS",
    "IMPURE_DOTTED_STDLIB_MODULES",
    "IMPURE_STDLIB_MODULES",
    "PYTHON",
    "TYPE_CHECKING_MESSAGE",
    "cached_module_imports",
    "is_imported_binding",
    "load_cached_sources",
    "module_bindings",
    "mount_facts",
    "scan_tree",
    "store_cached_sources",
]
