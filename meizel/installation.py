from __future__ import annotations

import sys
import tomllib
from functools import cache
from pathlib import Path

from meizel.graph.model import MeizelError

# Where this installation is: the project whose environment installed the checker, whose Node package
# supplies the TypeScript compiler. The project is the directory that holds the environment
# (`<project>/.venv`), the layout `uv` and `python -m venv .venv` produce; its `meizel.policy.toml` names the Node package
# under `[typescript] package-dir`, and a project that names none is its own Node package. The checked
# repository never supplies the compiler: a tree under judgment cannot change the analyzer judging it.
# See meizel/docs/frontend-deps.md.
TOOLCHAIN_ENV = "MEIZEL_TS_PACKAGE_DIR"


def project_root() -> Path:
    return Path(sys.prefix).resolve().parent


@cache
def typescript_toolchain() -> Path:
    root = project_root()
    policy = root / "meizel.policy.toml"
    if not policy.is_file():
        return root
    try:
        table = tomllib.loads(policy.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise MeizelError(f"{policy}: unreadable installation policy: {error}") from error
    section = table.get("typescript", {})
    named = section.get("package-dir", []) if isinstance(section, dict) else []
    if not isinstance(named, list) or not all(isinstance(item, str) for item in named):
        raise MeizelError(f"{policy}: [typescript] package-dir must be a list of strings")
    if len(named) > 1:
        raise MeizelError(f"{policy}: [typescript] package-dir names more than one Node package")
    return root / named[0] if named else root
