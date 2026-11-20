"""The Python frontend. What the checker reads of it from outside: the frontend, the tables its
purity rules judge a Python file against, the `TYPE_CHECKING` rule's two questions, and the record
a Python scan keeps of a file. The Python-specific code behind them stays in this package."""

from __future__ import annotations

from meizel.language.python.bindings import is_imported_binding, module_bindings
from meizel.language.python.cache import (
    cached_module_imports,
    load_cached_sources,
    store_cached_sources,
)
from meizel.language.python.fixtures import FixtureFunction, FixtureRequest, FixtureState
from meizel.language.python.frontend import PYTHON
from meizel.language.python.purity import (
    ALLOWED_STDLIB_MODULES,
    DEFAULT_IMPURE_CALLS,
    IMPURE_DOTTED_STDLIB_MODULES,
    IMPURE_STDLIB_MODULES,
)
from meizel.language.python.record import (
    InputListAppend,
    PythonRecord,
    decode_record,
    encode_record,
    python_record,
)
from meizel.language.python.rules import (
    type_checking_in_scope,
    type_checking_lines,
    type_checking_violations,
)
from meizel.language.python.scanner import scan_tree

__all__ = [
    "ALLOWED_STDLIB_MODULES",
    "DEFAULT_IMPURE_CALLS",
    "IMPURE_DOTTED_STDLIB_MODULES",
    "IMPURE_STDLIB_MODULES",
    "PYTHON",
    "FixtureFunction",
    "FixtureRequest",
    "FixtureState",
    "InputListAppend",
    "PythonRecord",
    "cached_module_imports",
    "decode_record",
    "encode_record",
    "is_imported_binding",
    "load_cached_sources",
    "module_bindings",
    "python_record",
    "scan_tree",
    "store_cached_sources",
    "type_checking_in_scope",
    "type_checking_lines",
    "type_checking_violations",
]
