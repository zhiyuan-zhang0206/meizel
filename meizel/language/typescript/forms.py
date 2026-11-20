"""The restricted forms the TypeScript frontend reports, and which declaration lets a file use them."""

from __future__ import annotations

__all__ = ["DYNAMIC_ATTR_FORMS", "EXTERNAL_FORMS", "restricted_hint"]

# The forms a file may use once `[external]` declares that it runs code from outside the repository.
EXTERNAL_FORMS = frozenset({"import()", "require()", "eval of source text", "Function constructor"})
# The forms a file may use once `[dynamic-attrs]` declares that it owns a name only the run knows.
DYNAMIC_ATTR_FORMS = frozenset({"dynamic global key"})

_LOADS = "a file that only loads declares its directories under [loads] in {manifest}"
_EXTERNAL = (
    "a file that runs code from outside the repository declares it under [external] with a reason"
)
_DYNAMIC = "a file that owns a global name only the run knows declares it under [dynamic-attrs] with a reason"
_HINTS = {
    "import()": "write the specifier as a string literal; " + _LOADS + "; " + _EXTERNAL,
    "require()": "write the specifier as a string literal; " + _LOADS + "; " + _EXTERNAL,
    "eval of source text": "pass the data, not code; " + _EXTERNAL,
    "Function constructor": "pass the data, not code; " + _EXTERNAL,
    "dynamic global key": "name the key (a literal, or a union of literals); " + _DYNAMIC,
    "export *": "name what is re-exported: `export { a, b } from ...`",
    "declare global": "move the declaration into a `.d.ts` declaration file",
    "declare module": "move the declaration into a `.d.ts` declaration file",
    "runtime rewrite of import": "inject the collaborator instead of rewriting an object an import bound",
}


# What to do about a restricted form: each form says only the declarations that can exempt it.
def restricted_hint(form: str, manifest: str) -> str:
    return _HINTS[form].replace("{manifest}", manifest)
