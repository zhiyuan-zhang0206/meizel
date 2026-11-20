from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from meizel.test_graph.impact import path_impacts
from meizel.test_graph.model import FileTestFacts, TestCheckout

__all__ = ["InputClosure", "input_closures"]


# The files whose content can change what one test file does. `unbounded` is why the graph could not
# bound them (`None` when it did): the closure is then every file of the tree, so a result is reused
# only for a tree no file of which differs.
@dataclass(frozen=True, slots=True)
class InputClosure:
    files: frozenset[str]
    unbounded: str | None = None


# The inverse of test selection: a file is in a test's closure exactly when changing that file alone
# selects the test, so a cached result is never reused where selection would run the test. The one
# difference is a test selection cannot bound (an unknown dependency, a read of the whole tree, a read
# of a path the graph does not anchor): selection runs it for every change, and its closure is the
# whole tree.
def input_closures(
    checkout: TestCheckout, facts_by_file: Mapping[str, FileTestFacts]
) -> dict[str, InputClosure]:
    impacts = path_impacts(checkout, facts_by_file)
    bounded: dict[str, set[str]] = {test: set() for test in checkout.collectable}
    for path, tests in impacts.by_path.items():
        for test in tests:
            bounded[test].add(path)
    return {
        test: (
            InputClosure(checkout.all_files, impacts.unbounded[test])
            if test in impacts.unbounded
            else InputClosure(frozenset(files))
        )
        for test, files in sorted(bounded.items())
    }
