"""The TypeScript frontend. What the checker reads of it from outside: the frontend, and the
`[typescript]` policy's scopes and files."""

from __future__ import annotations

from meizel.language.typescript.adapter import typescript_files, typescript_scopes
from meizel.language.typescript.frontend import TYPESCRIPT

__all__ = ["TYPESCRIPT", "typescript_files", "typescript_scopes"]
