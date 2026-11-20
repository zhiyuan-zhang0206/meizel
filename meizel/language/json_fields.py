"""The optional fields of a JSON object: a field that is absent reads as no entries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from meizel.language.json_containers import as_array, as_row

__all__ = ["opt_list", "opt_rows", "put_if"]


def opt_list(raw: Mapping[str, object], key: str) -> list[object]:
    return as_array(raw[key]) if key in raw else []


def opt_rows(raw: Mapping[str, object], key: str, size: int) -> list[list[object]]:
    if key not in raw:
        return []
    return [as_row(item, size) for item in as_array(raw[key])]


def put_if(out: dict[str, object], key: str, value: Sequence[object]) -> None:
    if value:
        out[key] = list(value)
