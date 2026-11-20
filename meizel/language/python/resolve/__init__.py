"""What a Python name refers to: lexical bindings, the modules of a repository, the files that import one another."""

from __future__ import annotations

from meizel.language.python.resolve.bindings import (
    ClassFacts,
    find_class,
    is_imported_binding,
    module_bindings,
    overridable_methods,
    provides,
    unambiguous_function_lines,
)
from meizel.language.python.resolve.impacted import python_reverse_closure
from meizel.language.python.resolve.imports import ImportAccess
from meizel.language.python.resolve.modules import PythonModules, python_modules
from meizel.language.python.resolve.scopes import (
    Scope,
    absolute_base,
    bind_target,
    collect_scope,
    dotted_chain,
    parameter_names,
)

__all__ = [
    "ClassFacts",
    "ImportAccess",
    "PythonModules",
    "Scope",
    "absolute_base",
    "bind_target",
    "collect_scope",
    "dotted_chain",
    "find_class",
    "is_imported_binding",
    "module_bindings",
    "overridable_methods",
    "parameter_names",
    "provides",
    "python_modules",
    "python_reverse_closure",
    "unambiguous_function_lines",
]
