# The JSON form of the records a scan produces: a `FileScan` and the `Sources` a run reads. A
# frontend that runs out of process speaks this form, and the scan cache stores it.

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from typing import Literal, TypeGuard

from meizel.graph.model import (
    Acquisition,
    AnyCollaboratorSite,
    Code,
    EntropySite,
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
from meizel.language.fixtures import FixtureFunction, FixtureRequest, FixtureState
from meizel.language.input_mutations import InputListAppend
from meizel.language.scan import FileScan
from meizel.source_text import object_of

__all__ = [
    "decode_file_scan",
    "decode_imports",
    "decode_sources",
    "encode_file_scan",
    "encode_imports",
    "encode_sources",
]

_COMMON_SCAN_KEYS = frozenset({"path", "facts", "imported", "symbols", "type_checking", "deps"})
_FACT_KINDS: dict[str, FactKind] = {k.value: k for k in FactKind}
_CODES: dict[str, Code] = {c.value: c for c in Code}
type _FixtureForm = Literal["parameter", "usefixtures", "call", "lookup"]


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _is_str_list(value: object) -> TypeGuard[list[str]]:
    return _is_array(value) and all(isinstance(x, str) for x in value)


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("expected string")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return _text(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise TypeError("expected int")
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _integer(value)


def _flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError("expected bool")
    return value


def _array(value: object) -> list[object]:
    if not _is_array(value):
        raise TypeError("expected list")
    return value


def _row(value: object, size: int) -> list[object]:
    items = _array(value)
    if len(items) != size:
        raise ValueError(f"expected {size} elements")
    return items


def _record(value: object) -> dict[str, object]:
    if not _is_object(value):
        raise TypeError("expected object")
    return value


def _fixture_form(value: object) -> _FixtureForm:
    text = _text(value)
    if text == "parameter":
        return "parameter"
    if text == "usefixtures":
        return "usefixtures"
    if text == "call":
        return "call"
    if text == "lookup":
        return "lookup"
    raise ValueError(f"unknown fixture form: {text}")


def _put_if(out: dict[str, object], key: str, value: Sequence[object]) -> None:
    if value:
        out[key] = list(value)


def _encode_fixtures_raw(fx: FixtureState) -> dict[str, object]:
    out: dict[str, object] = {}
    _put_if(out, "defs", sorted(fx.defs))
    _put_if(
        out,
        "requests",
        [[r.name, r.line, r.skip_self, r.requester_line, r.form] for r in fx.requests],
    )
    _put_if(out, "plugins", [[name, line] for name, line in fx.plugins])
    _put_if(
        out,
        "functions",
        [
            [fn.name, fn.line, fn.registered, fn.module_owned, fn.parameters_known]
            for fn in fx.functions
        ],
    )
    return out


def _scan_to_raw_edges(scan: FileScan, out: dict[str, object]) -> None:
    _put_if(
        out,
        "facts",
        [[f.src, f.dst, f.line, f.kind.value, list(f.names), f.detail] for f in scan.facts],
    )
    _put_if(out, "restricted", [[r.line, r.form, r.detail] for r in scan.restricted])
    _put_if(
        out,
        "patches",
        [[p.line, p.form, p.target, p.code.value, p.imported] for p in scan.patches],
    )
    _put_if(out, "problems", [[p.line, p.code.value, p.message] for p in scan.problems])
    fx_raw = _encode_fixtures_raw(scan.fixtures)
    if fx_raw:
        out["fixtures"] = fx_raw
    _put_if(out, "imported", sorted(scan.imported))


def _scan_to_raw_sites(scan: FileScan, out: dict[str, object]) -> None:
    _put_if(
        out,
        "purity",
        [[p.line, p.code.value, p.key, p.message, p.hint] for p in scan.purity],
    )
    _put_if(
        out,
        "enum_subsets",
        [[u.line, u.cls_name, list(u.members)] for u in scan.enum_subsets],
    )
    _put_if(
        out,
        "input_appends",
        [[a.line, a.function, a.parameter] for a in scan.input_appends],
    )
    _put_if(out, "ambient", [[a.line, str(a.kind), a.target] for a in scan.ambient])
    _put_if(out, "entropy", [[e.line, e.what] for e in scan.entropy])
    _put_if(out, "type_casts", [[c.line, c.column, c.qualname] for c in scan.type_casts])
    _put_if(
        out,
        "any_collaborators",
        [[c.line, c.column, c.qualname, c.slot, c.role] for c in scan.any_collaborators],
    )
    _put_if(out, "type_checking", list(scan.type_checking))
    _put_if(out, "symbols", [[s[0], s[1], s[2]] for s in scan.symbols])
    _put_if(out, "deps", list(scan.deps))
    _put_if(out, "injected", list(scan.injected))


def _scan_to_raw(scan: FileScan) -> dict[str, object]:
    out: dict[str, object] = {"path": scan.path}
    _scan_to_raw_edges(scan, out)
    _scan_to_raw_sites(scan, out)
    return out


def _opt_list(raw: Mapping[str, object], key: str) -> list[object]:
    return _array(raw[key]) if key in raw else []


def _opt_rows(raw: Mapping[str, object], key: str, size: int) -> list[list[object]]:
    if key not in raw:
        return []
    return [_row(item, size) for item in _array(raw[key])]


def _decode_fixtures(raw: Mapping[str, object]) -> FixtureState:
    if "fixtures" not in raw:
        return FixtureState()
    fx = _record(raw["fixtures"])
    defs = {_text(item) for item in _opt_list(fx, "defs")}
    requests = [
        FixtureRequest(
            _text(name),
            _integer(line),
            skip_self=_flag(skip_self),
            requester_line=_integer(req_line),
            form=_fixture_form(form),
        )
        for name, line, skip_self, req_line, form in _opt_rows(fx, "requests", 5)
    ]
    plugins = [(_text(name), _integer(line)) for name, line in _opt_rows(fx, "plugins", 2)]
    functions = [
        FixtureFunction(
            _text(name), _integer(line), _optional_text(reg), _flag(owned), _flag(known)
        )
        for name, line, reg, owned, known in _opt_rows(fx, "functions", 5)
    ]
    return FixtureState(defs=defs, requests=requests, plugins=plugins, functions=functions)


def _fact_from_row(item: object) -> Fact:
    src, dst, line, kind, names, detail = _row(item, 6)
    if (
        isinstance(src, str)
        and isinstance(dst, str)
        and type(line) is int
        and isinstance(kind, str)
        and _is_str_list(names)
        and isinstance(detail, str)
    ):
        return Fact(src, dst, line, _FACT_KINDS[kind], tuple(names), detail)
    raise TypeError("malformed fact row")


def _decode_facts(raw: Mapping[str, object]) -> list[Fact]:
    if "facts" not in raw:
        return []
    return [_fact_from_row(item) for item in _array(raw["facts"])]


def _decode_patches(raw: Mapping[str, object]) -> list[Patch]:
    return [
        Patch(_integer(line), _text(form), _text(target), _CODES[_text(code)], imported=_flag(imp))
        for line, form, target, code, imp in _opt_rows(raw, "patches", 5)
    ]


def _decode_purity(raw: Mapping[str, object]) -> list[PurityItem]:
    return [
        PurityItem(_integer(line), _CODES[_text(code)], _text(key), _text(msg), _text(hint))
        for line, code, key, msg, hint in _opt_rows(raw, "purity", 5)
    ]


def _decode_collaborators(raw: Mapping[str, object]) -> list[AnyCollaboratorSite]:
    return [
        AnyCollaboratorSite(_integer(line), _integer(col), _text(qual), _text(slot), _text(role))
        for line, col, qual, slot, role in _opt_rows(raw, "any_collaborators", 5)
    ]


def _symbol_from_row(item: object) -> tuple[str, int, int]:
    name, start, end = _row(item, 3)
    if isinstance(name, str) and type(start) is int and type(end) is int:
        return (name, start, end)
    raise TypeError("malformed symbol row")


def _decode_symbols(raw: Mapping[str, object]) -> tuple[tuple[str, int, int], ...]:
    if "symbols" not in raw:
        return ()
    return tuple(_symbol_from_row(item) for item in _array(raw["symbols"]))


def _decode_common_scan(raw: Mapping[str, object]) -> FileScan:
    return FileScan(
        _text(raw["path"]),
        facts=_decode_facts(raw),
        imported={_text(item) for item in _opt_list(raw, "imported")},
        type_checking=tuple(_integer(item) for item in _opt_list(raw, "type_checking")),
        symbols=_decode_symbols(raw),
        deps=tuple(_text(item) for item in _opt_list(raw, "deps")),
    )


def _scan_from_raw(value: object, kinds: Collection[str]) -> FileScan:
    raw = _record(value)
    if raw.keys() <= _COMMON_SCAN_KEYS:
        return _decode_common_scan(raw)
    return FileScan(
        _text(raw["path"]),
        facts=_decode_facts(raw),
        restricted=[
            Restricted(_integer(line), _text(form), _text(detail))
            for line, form, detail in _opt_rows(raw, "restricted", 3)
        ],
        patches=_decode_patches(raw),
        problems=[
            Problem(_integer(line), _CODES[_text(code)], _text(msg))
            for line, code, msg in _opt_rows(raw, "problems", 3)
        ],
        fixtures=_decode_fixtures(raw),
        imported={_text(item) for item in _opt_list(raw, "imported")},
        purity=_decode_purity(raw),
        enum_subsets=[
            EnumSubsetUse(_integer(line), _text(cls), tuple(_text(m) for m in _array(members)))
            for line, cls, members in _opt_rows(raw, "enum_subsets", 3)
        ],
        input_appends=[
            InputListAppend(_integer(line), _text(fn), _text(param))
            for line, fn, param in _opt_rows(raw, "input_appends", 3)
        ],
        ambient=[
            Acquisition(_integer(line), known_kind(_text(kind), kinds), _text(target))
            for line, kind, target in _opt_rows(raw, "ambient", 3)
        ],
        entropy=[
            EntropySite(_integer(line), _text(what)) for line, what in _opt_rows(raw, "entropy", 2)
        ],
        type_casts=[
            TypeCastSite(_integer(line), _integer(col), _text(qual))
            for line, col, qual in _opt_rows(raw, "type_casts", 3)
        ],
        any_collaborators=_decode_collaborators(raw),
        type_checking=tuple(_integer(item) for item in _opt_list(raw, "type_checking")),
        symbols=_decode_symbols(raw),
        deps=tuple(_text(item) for item in _opt_list(raw, "deps")),
        injected=tuple(_text(item) for item in _opt_list(raw, "injected")),
    )


def encode_file_scan(scan: FileScan) -> str:
    return json.dumps(_scan_to_raw(scan), separators=(",", ":"))


def decode_file_scan(text: str, kinds: Collection[str]) -> FileScan:
    raw = object_of(json.loads, text)
    return _scan_from_raw(raw, kinds)


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
    raw = _record(raw_obj)
    names = {_text(k): _text(v) for k, v in (_row(item, 2) for item in _array(raw["names"]))}
    calls = {_text(k): _text(v) for k, v in (_row(item, 2) for item in _array(raw["calls"]))}
    uses = frozenset(_text(item) for item in _array(raw["uses"]))
    unless = {
        _text(k): Unless(_text(param), _optional_int(pos))
        for k, param, pos in (_row(item, 3) for item in _array(raw["unless"]))
    }
    return Sources(names=names, calls=calls, uses=uses, unless=unless)


def encode_imports(imports: Mapping[str, str]) -> str:
    return json.dumps(imports, separators=(",", ":"))


def decode_imports(text: str) -> dict[str, str] | None:
    try:
        raw = object_of(json.loads, text)
        return {_text(k): _text(v) for k, v in _record(raw).items()}
    except (ValueError, TypeError, KeyError):
        return None
