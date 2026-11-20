# The JSON form of the records a scan produces: a `FileScan` and the `Sources` a run reads. A
# frontend that runs out of process speaks this form, and the scan cache stores it.

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping

from meizel.graph.model import (
    Acquisition,
    AnyCollaboratorSite,
    Code,
    EnumSubsetUse,
    Fact,
    FactKind,
    Patch,
    Problem,
    PurityItem,
    Restricted,
    Sources,
    TypeCastSite,
    Unless,
    known_kind,
)
from meizel.language.file_scan import FileScan
from meizel.language.json_containers import as_array, as_record, as_row, is_str_list
from meizel.language.json_fields import opt_list, opt_rows, put_if
from meizel.language.json_scalars import as_flag, as_int, as_optional_int, as_text
from meizel.source_text import object_of

__all__ = [
    "ExtraDecoder",
    "ExtraEncoder",
    "decode_file_scan",
    "decode_imports",
    "decode_sources",
    "encode_file_scan",
    "encode_imports",
    "encode_sources",
]

_COMMON_SCAN_KEYS = frozenset({"path", "facts", "symbols", "extra"})
_FACT_KINDS: dict[str, FactKind] = {k.value: k for k in FactKind}
_CODES: dict[str, Code] = {c.value: c for c in Code}


def _scan_to_raw_edges(scan: FileScan, out: dict[str, object]) -> None:
    put_if(
        out,
        "facts",
        [[f.src, f.dst, f.line, f.kind.value, list(f.names), f.detail] for f in scan.facts],
    )
    put_if(out, "restricted", [[r.line, r.form, r.detail] for r in scan.restricted])
    put_if(
        out,
        "patches",
        [[p.line, p.form, p.target, p.code.value, p.imported] for p in scan.patches],
    )
    put_if(out, "problems", [[p.line, p.code.value, p.message] for p in scan.problems])


def _scan_to_raw_sites(scan: FileScan, out: dict[str, object]) -> None:
    put_if(
        out,
        "purity",
        [[p.line, p.code.value, p.key, p.message, p.hint] for p in scan.purity],
    )
    put_if(
        out,
        "enum_subsets",
        [[u.line, u.cls_name, list(u.members)] for u in scan.enum_subsets],
    )
    put_if(out, "ambient", [[a.line, str(a.kind), a.target] for a in scan.ambient])
    put_if(out, "type_casts", [[c.line, c.column, c.qualname] for c in scan.type_casts])
    put_if(
        out,
        "any_collaborators",
        [[c.line, c.column, c.qualname, c.slot, c.role] for c in scan.any_collaborators],
    )
    put_if(out, "symbols", [[s[0], s[1], s[2]] for s in scan.symbols])
    put_if(out, "injected", list(scan.injected))


def _scan_to_raw(scan: FileScan, encode_extra: ExtraEncoder | None) -> dict[str, object]:
    out: dict[str, object] = {"path": scan.path}
    _scan_to_raw_edges(scan, out)
    _scan_to_raw_sites(scan, out)
    extra = None if encode_extra is None else encode_extra(scan.extra)
    if extra is not None:
        out["extra"] = extra
    return out


def _fact_from_row(item: object) -> Fact:
    src, dst, line, kind, names, detail = as_row(item, 6)
    if (
        isinstance(src, str)
        and isinstance(dst, str)
        and type(line) is int
        and isinstance(kind, str)
        and is_str_list(names)
        and isinstance(detail, str)
    ):
        return Fact(src, dst, line, _FACT_KINDS[kind], tuple(names), detail)
    raise TypeError("malformed fact row")


def _decode_facts(raw: Mapping[str, object]) -> list[Fact]:
    if "facts" not in raw:
        return []
    return [_fact_from_row(item) for item in as_array(raw["facts"])]


def _decode_patches(raw: Mapping[str, object]) -> list[Patch]:
    return [
        Patch(
            as_int(line),
            as_text(form),
            as_text(target),
            _CODES[as_text(code)],
            imported=as_flag(imp),
        )
        for line, form, target, code, imp in opt_rows(raw, "patches", 5)
    ]


def _decode_purity(raw: Mapping[str, object]) -> list[PurityItem]:
    return [
        PurityItem(as_int(line), _CODES[as_text(code)], as_text(key), as_text(msg), as_text(hint))
        for line, code, key, msg, hint in opt_rows(raw, "purity", 5)
    ]


def _decode_collaborators(raw: Mapping[str, object]) -> list[AnyCollaboratorSite]:
    return [
        AnyCollaboratorSite(as_int(line), as_int(col), as_text(qual), as_text(slot), as_text(role))
        for line, col, qual, slot, role in opt_rows(raw, "any_collaborators", 5)
    ]


def _symbol_from_row(item: object) -> tuple[str, int, int]:
    name, start, end = as_row(item, 3)
    if isinstance(name, str) and type(start) is int and type(end) is int:
        return (name, start, end)
    raise TypeError("malformed symbol row")


def _decode_symbols(raw: Mapping[str, object]) -> tuple[tuple[str, int, int], ...]:
    if "symbols" not in raw:
        return ()
    return tuple(_symbol_from_row(item) for item in as_array(raw["symbols"]))


def _decode_extra(raw: Mapping[str, object], decode_extra: ExtraDecoder | None) -> object:
    if decode_extra is None or "extra" not in raw:
        return None
    return decode_extra(as_record(raw["extra"]))


def _decode_common_scan(raw: Mapping[str, object], decode_extra: ExtraDecoder | None) -> FileScan:
    return FileScan(
        as_text(raw["path"]),
        facts=_decode_facts(raw),
        symbols=_decode_symbols(raw),
        extra=_decode_extra(raw, decode_extra),
    )


def _scan_from_raw(
    value: object, kinds: Collection[str], decode_extra: ExtraDecoder | None
) -> FileScan:
    raw = as_record(value)
    if raw.keys() <= _COMMON_SCAN_KEYS:
        return _decode_common_scan(raw, decode_extra)
    return FileScan(
        as_text(raw["path"]),
        facts=_decode_facts(raw),
        restricted=[
            Restricted(as_int(line), as_text(form), as_text(detail))
            for line, form, detail in opt_rows(raw, "restricted", 3)
        ],
        patches=_decode_patches(raw),
        problems=[
            Problem(as_int(line), _CODES[as_text(code)], as_text(msg))
            for line, code, msg in opt_rows(raw, "problems", 3)
        ],
        purity=_decode_purity(raw),
        enum_subsets=[
            EnumSubsetUse(as_int(line), as_text(cls), tuple(as_text(m) for m in as_array(members)))
            for line, cls, members in opt_rows(raw, "enum_subsets", 3)
        ],
        ambient=[
            Acquisition(as_int(line), known_kind(as_text(kind), kinds), as_text(target))
            for line, kind, target in opt_rows(raw, "ambient", 3)
        ],
        type_casts=[
            TypeCastSite(as_int(line), as_int(col), as_text(qual))
            for line, col, qual in opt_rows(raw, "type_casts", 3)
        ],
        any_collaborators=_decode_collaborators(raw),
        symbols=_decode_symbols(raw),
        injected=tuple(as_text(item) for item in opt_list(raw, "injected")),
        extra=_decode_extra(raw, decode_extra),
    )


# The frontend's own record of a file (`FileScan.extra`) as a JSON object, and back: the codec
# carries it without reading it.
type ExtraEncoder = Callable[[object], dict[str, object] | None]
type ExtraDecoder = Callable[[Mapping[str, object]], object]


def encode_file_scan(scan: FileScan, encode_extra: ExtraEncoder | None = None) -> str:
    return json.dumps(_scan_to_raw(scan, encode_extra), separators=(",", ":"))


def decode_file_scan(
    text: str, kinds: Collection[str], decode_extra: ExtraDecoder | None = None
) -> FileScan:
    raw = object_of(json.loads, text)
    return _scan_from_raw(raw, kinds, decode_extra)


def encode_sources(sources: Sources) -> str:
    payload = {
        "names": [[k, str(v)] for k, v in sorted(sources.names.items())],
        "calls": [[k, str(v)] for k, v in sorted(sources.calls.items())],
        "uses": sorted(sources.uses),
        "unless": [[k, u.parameter, u.position] for k, u in sorted(sources.unless.items())],
    }
    return json.dumps(payload, separators=(",", ":"))


def decode_sources(text: str) -> Sources:
    raw_obj = object_of(json.loads, text)
    raw = as_record(raw_obj)
    names = {
        as_text(k): as_text(v) for k, v in (as_row(item, 2) for item in as_array(raw["names"]))
    }
    calls = {
        as_text(k): as_text(v) for k, v in (as_row(item, 2) for item in as_array(raw["calls"]))
    }
    uses = frozenset(as_text(item) for item in as_array(raw["uses"]))
    unless = {
        as_text(k): Unless(as_text(param), as_optional_int(pos))
        for k, param, pos in (as_row(item, 3) for item in as_array(raw["unless"]))
    }
    return Sources(names=names, calls=calls, uses=uses, unless=unless)


def encode_imports(imports: Mapping[str, str]) -> str:
    return json.dumps(imports, separators=(",", ":"))


def decode_imports(text: str) -> dict[str, str] | None:
    try:
        raw = object_of(json.loads, text)
        return {as_text(k): as_text(v) for k, v in as_record(raw).items()}
    except (ValueError, TypeError, KeyError):
        return None
