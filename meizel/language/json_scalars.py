"""The scalar JSON values a record is read from: each reader refuses a value of another shape."""

from __future__ import annotations

__all__ = ["as_flag", "as_int", "as_optional_int", "as_optional_text", "as_text"]


def as_text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("expected string")
    return value


def as_optional_text(value: object) -> str | None:
    if value is None:
        return None
    return as_text(value)


def as_int(value: object) -> int:
    if type(value) is not int:
        raise TypeError("expected int")
    return value


def as_optional_int(value: object) -> int | None:
    if value is None:
        return None
    return as_int(value)


def as_flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError("expected bool")
    return value
