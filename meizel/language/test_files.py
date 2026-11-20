"""Which paths are test files: the convention both languages share."""

from __future__ import annotations

__all__ = ["is_test_file"]


def is_test_file(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    if name.endswith((".ts", ".tsx", ".mts", ".cts")):
        return (
            name.endswith(
                (
                    ".test.ts",
                    ".test.tsx",
                    ".spec.ts",
                    ".spec.tsx",
                    "-test-mock.ts",
                    "-test-mock.tsx",
                    ".test.mts",
                    ".test.cts",
                    ".spec.mts",
                    ".spec.cts",
                    "-test-mock.mts",
                    "-test-mock.cts",
                )
            )
            or "tests" in parts[:-1]
            or "test-support" in parts[:-1]
        )
    return name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py")
