"""The JSON arrays and objects a record is read from: each reader refuses a value of another shape."""

from __future__ import annotations

from typing import TypeGuard

__all__ = ["as_array", "as_record", "as_row", "is_str_list"]


def _is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def is_str_list(value: object) -> TypeGuard[list[str]]:
    return _is_array(value) and all(isinstance(x, str) for x in value)


def as_array(value: object) -> list[object]:
    if not _is_array(value):
        raise TypeError("expected list")
    return value


def as_record(value: object) -> dict[str, object]:
    if not _is_object(value):
        raise TypeError("expected object")
    return value


def as_row(value: object, size: int) -> list[object]:
    items = as_array(value)
    if len(items) != size:
        raise ValueError(f"expected {size} elements")
    return items
