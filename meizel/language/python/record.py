"""What the Python frontend records of a file beyond the checker's record: pytest fixtures, the
names a module imports, the lists a function appends to, the entropy sites, the `TYPE_CHECKING`
blocks and the files its scan read. The checker never reads it; the Python rules and the scan
cache do, and `encode_record` / `decode_record` are its JSON form."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from meizel.graph.model import EntropySite
from meizel.language.file_scan import FileScan
from meizel.language.json_containers import as_record
from meizel.language.json_fields import opt_list, opt_rows, put_if
from meizel.language.json_scalars import as_flag, as_int, as_optional_text, as_text
from meizel.language.python.fixtures import FixtureFunction, FixtureRequest, FixtureState

__all__ = [
    "InputListAppend",
    "PythonRecord",
    "decode_record",
    "encode_record",
    "python_record",
]

type _FixtureForm = Literal["parameter", "usefixtures", "call", "lookup"]


@dataclass(frozen=True, slots=True)
class InputListAppend:
    line: int
    function: str
    parameter: str


@dataclass(frozen=True, slots=True)
class PythonRecord:
    fixtures: FixtureState = field(default_factory=FixtureState)
    imported: set[str] = field(default_factory=set[str])
    input_appends: list[InputListAppend] = field(default_factory=list[InputListAppend])
    entropy: list[EntropySite] = field(default_factory=list[EntropySite])
    type_checking: tuple[int, ...] = ()
    deps: tuple[str, ...] = ()


# The Python record of a scan: a file the Python frontend did not read has none to give.
def python_record(scan: FileScan) -> PythonRecord:
    return scan.extra if isinstance(scan.extra, PythonRecord) else PythonRecord()


def _fixture_form(value: object) -> _FixtureForm:
    text = as_text(value)
    if text == "parameter":
        return "parameter"
    if text == "usefixtures":
        return "usefixtures"
    if text == "call":
        return "call"
    if text == "lookup":
        return "lookup"
    raise ValueError(f"unknown fixture form: {text}")


def _encode_fixtures_raw(fx: FixtureState) -> dict[str, object]:
    out: dict[str, object] = {}
    put_if(out, "defs", sorted(fx.defs))
    put_if(
        out,
        "requests",
        [[r.name, r.line, r.skip_self, r.requester_line, r.form] for r in fx.requests],
    )
    put_if(out, "plugins", [[name, line] for name, line in fx.plugins])
    put_if(
        out,
        "functions",
        [
            [fn.name, fn.line, fn.registered, fn.module_owned, fn.parameters_known]
            for fn in fx.functions
        ],
    )
    return out


def _decode_fixtures(raw: Mapping[str, object]) -> FixtureState:
    if "fixtures" not in raw:
        return FixtureState()
    fx = as_record(raw["fixtures"])
    defs = {as_text(item) for item in opt_list(fx, "defs")}
    requests = [
        FixtureRequest(
            as_text(name),
            as_int(line),
            skip_self=as_flag(skip_self),
            requester_line=as_int(req_line),
            form=_fixture_form(form),
        )
        for name, line, skip_self, req_line, form in opt_rows(fx, "requests", 5)
    ]
    plugins = [(as_text(name), as_int(line)) for name, line in opt_rows(fx, "plugins", 2)]
    functions = [
        FixtureFunction(
            as_text(name), as_int(line), as_optional_text(reg), as_flag(owned), as_flag(known)
        )
        for name, line, reg, owned, known in opt_rows(fx, "functions", 5)
    ]
    return FixtureState(defs=defs, requests=requests, plugins=plugins, functions=functions)


def encode_record(extra: object) -> dict[str, object] | None:
    if not isinstance(extra, PythonRecord):
        return None
    out: dict[str, object] = {}
    fx_raw = _encode_fixtures_raw(extra.fixtures)
    if fx_raw:
        out["fixtures"] = fx_raw
    put_if(out, "imported", sorted(extra.imported))
    put_if(out, "input_appends", [[a.line, a.function, a.parameter] for a in extra.input_appends])
    put_if(out, "entropy", [[e.line, e.what] for e in extra.entropy])
    put_if(out, "type_checking", list(extra.type_checking))
    put_if(out, "deps", list(extra.deps))
    return out


def decode_record(raw: Mapping[str, object]) -> PythonRecord:
    return PythonRecord(
        fixtures=_decode_fixtures(raw),
        imported={as_text(item) for item in opt_list(raw, "imported")},
        input_appends=[
            InputListAppend(as_int(line), as_text(fn), as_text(param))
            for line, fn, param in opt_rows(raw, "input_appends", 3)
        ],
        entropy=[
            EntropySite(as_int(line), as_text(what)) for line, what in opt_rows(raw, "entropy", 2)
        ],
        type_checking=tuple(as_int(item) for item in opt_list(raw, "type_checking")),
        deps=tuple(as_text(item) for item in opt_list(raw, "deps")),
    )
