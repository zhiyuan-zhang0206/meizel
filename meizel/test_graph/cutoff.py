from __future__ import annotations

__all__ = ["package_local_tests"]


# The one question both test selectors still ask of this module: which collectable tests belong to
# the package that owns `path`. The interface cutoff that gave the module its name is gone - an AST
# fingerprint deciding that an unchanged signature means an unchanged behavior. It was removed
# from CI's selector once a test was shown to assert behavior, not a signature; `meizel impacted`
# never used it (it is a reverse import closure); and its last consumer was removed,
# `meizel tests --base-ref`, which keeps the flag for deleted-path recovery only.
def package_local_tests(
    path: str,
    test_dirs: frozenset[str],
    collectable: frozenset[str],
    *,
    include_root_tests: bool = False,
) -> set[str]:
    directory = path.rpartition("/")[0]
    while directory:
        tests_dir = directory if directory.rpartition("/")[2] == "tests" else f"{directory}/tests"
        if tests_dir in test_dirs:
            prefix = f"{tests_dir}/"
            return {test for test in collectable if test.startswith(prefix)}
        directory = directory.rpartition("/")[0]
    if include_root_tests and "tests" in test_dirs:
        return {test for test in collectable if test.startswith("tests/")}
    return set()
