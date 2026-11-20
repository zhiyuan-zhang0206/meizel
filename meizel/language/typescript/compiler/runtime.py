from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from meizel.allowances import Policy
from meizel.graph.model import MeizelError, Sources
from meizel.graph.universe import Universe
from meizel.language import fixtures
from meizel.language.typescript.compiler.config import load_ts_config
from meizel.language.typescript.compiler.decode import decode_batch
from meizel.language.typescript.compiler.model import TsScan
from meizel.lint_common import run_node_analyzer


# See meizel/docs/checker/typescript.md.
def scan_batch(
    universe: Universe, contents: dict[str, str], policy: Policy, sources: Sources
) -> dict[str, TsScan]:
    if not contents:
        return {}
    config = load_ts_config(policy)
    options = asdict(config)
    options["impure_calls"] = sorted(config.impure_calls)
    options["impure_hooks"] = sorted(config.impure_hooks)
    request = {
        "root": str(universe.root),
        "files": sorted(universe.files),
        "sources": contents,
        "config": options,
        "tests": [path for path in contents if fixtures.is_test_file(path)],
        "ambient": {"names": sources.names, "calls": sources.calls},
    }
    producer = Path(__file__).with_name("producer.mjs")
    # The compiler comes from this tool's own frontend install, never the checked repository's: the
    # checker runs against repositories that have no frontend at all, and a tree beside the inspected
    # code would be one more thing that code could change under the analysis.
    # See meizel/docs/frontend-deps.md.
    # The tree is the reader, not the directory read: its predicates take the path they are asked
    # about, so the preflight still observes this installation's frontend and never the checked
    # repository's. A strict module holds the checkout as data (`universe.repo`), and the tree is
    # how it holds one without importing the shell that runs git.
    output = run_node_analyzer(
        universe.repo.tree,
        producer,
        json.dumps(request),
        frontend=universe.repo.tree.toolchain(),
    )
    try:
        return decode_batch(output, frozenset(contents), policy.reader_kinds)
    except (TypeError, ValueError) as error:
        raise MeizelError(f"invalid TypeScript compiler result: {error}") from error
