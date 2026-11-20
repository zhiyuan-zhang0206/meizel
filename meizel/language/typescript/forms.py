"""The restricted forms the TypeScript frontend reports, and which declaration lets a file use them."""

from __future__ import annotations

__all__ = ["DYNAMIC_ATTR_FORMS", "EXTERNAL_FORMS"]

# The forms a file may use once `[external]` declares that it runs code from outside the repository.
EXTERNAL_FORMS = frozenset({"import()", "require()", "eval of source text", "Function constructor"})
# The forms a file may use once `[dynamic-attrs]` declares that it owns a name only the run knows.
DYNAMIC_ATTR_FORMS = frozenset({"dynamic global key"})
