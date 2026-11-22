# The checker's process entry: the only code that asks where this checkout and this installation
# are. It parses one argv, opens the single repository handle every command is handed, and gives
# the command layer the two readers only a shell can hold (the roles manifest and a file the argv
# names). Everything below it takes those values.
from __future__ import annotations

import os
import platform
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from meizel.checkout import GitRepo, read_roles, read_text, source_tree, toplevel
from meizel.contracts import cli
from meizel.frontend_deps import FrontendDepsError
from meizel.graph.model import MeizelError

__all__ = ["main", "open_repository"]


# The repository handle the commands are handed, over `root`. The entry owns this seat: a caller
# that needs the same handle (a test driving the CLI) opens it here instead of building its own.
def open_repository(root: Path) -> GitRepo:
    return GitRepo(root)


# A target as argv typed it, resolved against the directory this entry resolved — the repository
# when `--repo` names one, the working directory otherwise — and expressed relative to `root`. Only
# the entry may resolve: a command below it holds neither the working directory nor the checkout
# root, so resolving there would repeat the read in every one of its seven call sites.
def relative_targets(root: Path, base: Path) -> Callable[[str], str]:
    def relative(raw: str) -> str:
        resolved = (base / raw).resolve()
        try:
            rel = resolved.relative_to(root)
        except ValueError as error:
            raise MeizelError(f"{raw}: outside the repository {root}") from error
        return "" if str(rel) == "." else rel.as_posix()

    return relative


# What a test result depends on besides the files it reads: the interpreter, the platform and the
# values of the environment variables a repository declares under `[test-cache] env`.
def host_environment(declared: Sequence[str]) -> dict[str, str]:
    environment = {
        "python": sys.version,
        "implementation": sys.implementation.name,
        "platform": platform.system(),
        "machine": platform.machine(),
    }
    for name in declared:
        environment[f"env:{name}"] = os.environ.get(name, "")
    return environment


# The two namespace fields the entry reads. `parse_args` returns an `argparse.Namespace`, whose
# attributes are `Any`, so they are read once into typed values through the checker's own reader
# (`contracts.cli.read_args`, which also refuses a value of the wrong type).
@dataclass(frozen=True)
class _EntryOptions:
    jobs: int | None
    repo: Path | None


# The interpreter the standard-library tables were judged on: which modules are the standard
# library's, and what each public name of a channel module reads (`meizel.language.python.surface`). A
# newer interpreter adds names no table has judged, so the checker refuses to answer there rather
# than judge them by a default.
SUPPORTED_PYTHON = (3, 12)


def unsupported_python(version: tuple[int, int]) -> str | None:
    if version == SUPPORTED_PYTHON:
        return None
    wanted = ".".join(map(str, SUPPORTED_PYTHON))
    return (
        f"the standard-library tables are judged on Python {wanted}; this is "
        f"{'.'.join(map(str, version))}, whose new names no table has judged — run meizel on {wanted}"
    )


# Run one checker command from argv and return the process exit status.
def main(argv: list[str]) -> int:
    args = cli.build_parser().parse_args(argv)
    if (refused := unsupported_python(sys.version_info[:2])) is not None:
        print(f"meizel: {refused}", file=sys.stderr)
        return 2
    options = cli.read_args(args, _EntryOptions)
    # The one place the processor count is read: below the entry, `jobs=None` is serial.
    jobs = options.jobs if options.jobs is not None else min(os.cpu_count() or 1, 8)
    args.jobs = jobs
    try:
        base = options.repo if options.repo is not None else Path.cwd()
        # The one repository seat of the command: this checkout, read through one value that the
        # commands are handed instead of a path they would build their own from. A command that
        # judges reads a snapshot of it (`repo.universe()`).
        repo = open_repository(options.repo if options.repo is not None else toplevel(base))
        root = repo.root.resolve()
        deps = cli.CommandDeps(
            read_roles=read_roles,
            read_text=read_text,
            relative_target=relative_targets(root, base),
            source_tree=source_tree,
            today=datetime.now(UTC).date().isoformat(),
            environment=host_environment,
        )
        return cli.dispatch(repo, base, args, deps)
    except FrontendDepsError as error:
        print(f"meizel: {error}", file=sys.stderr)
        return 3
    except MeizelError as error:
        print(f"meizel: {error}", file=sys.stderr)
        return 2
