# The restricted TypeScript forms, found in one file by the compiler's symbols (docs/checker/restricted/
# restricted-typescript.md). Each case is the source and the (line, form) pairs it must report.
from __future__ import annotations

from pathlib import Path

import pytest

from meizel.allowances import Policy
from meizel.checkout import GitRepo
from meizel.graph.model import Sources
from meizel.graph.universe import Universe
from meizel.language.typescript.compiler import scan_batch

DEP = "export const dep = { a: 1 };\nexport class Kind {}\nexport const area: 'x' | 'y' = 'x';\n"


def _forms(tmp_path: Path, source: str, name: str = "owner.ts") -> list[tuple[int, str]]:
    files = {"dep.ts": DEP, name: source}
    universe = Universe(GitRepo(tmp_path), list(files))
    scans = scan_batch(universe, files, Policy(), Sources())
    return [(item.line, item.form) for item in scans[name].restricted]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("eval('1');", [(1, "eval of source text")]),
        ("const run = eval;\nrun('1');", [(1, "eval of source text")]),
        ("(0, eval)('1');", [(1, "eval of source text")]),
        ("globalThis.eval('1');", [(1, "eval of source text")]),
        ("window.eval('1');", [(1, "eval of source text")]),
        ("const f = new Function('a', 'return a');", [(1, "Function constructor")]),
        ("const f = Function('a');", [(1, "Function constructor")]),
        ("const f = globalThis.Function('a');", [(1, "Function constructor")]),
        # A local `eval`, a property called `eval`, and `Function` as a type or a test are not it.
        ("const f = (eval: string) => eval;", []),
        ("const o = { eval: 1 };\nconst n = o.eval;", []),
        ("const t: Function = () => 1;\nexport const is = t instanceof Function;", []),
        ("export const kind = typeof eval;", []),
    ],
)
def test_source_text_handed_to_the_engine_is_restricted(
    tmp_path: Path, source: str, expected: list[tuple[int, str]]
) -> None:
    assert _forms(tmp_path, source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("export const f = (key: string) => window[key];", [(1, "dynamic global key")]),
        ("export const f = (key: string) => globalThis[key];", [(1, "dynamic global key")]),
        ("export const f = (key: string) => self[`on${key}`];", [(1, "dynamic global key")]),
        # Stated: a literal, a const, a union of literals, an imported constant of such a type.
        ("export const v = globalThis['name'];", []),
        ("const k = 'name' as const;\nexport const v = window[k];", []),
        ("export const f = (key: 'a' | 'b') => window[key];", []),
        ("import { area } from './dep';\nexport const v = window[area];", []),
        # Not the global: a parameter called `window`, or any other object.
        ("export const f = (window: number[]) => window[0];", []),
        ("export const f = (o: Record<string, number>, key: string) => o[key];", []),
    ],
)
def test_a_global_object_is_not_read_through_a_key_the_source_does_not_state(
    tmp_path: Path, source: str, expected: list[tuple[int, str]]
) -> None:
    assert _forms(tmp_path, source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("export * from './dep';", [(1, "export *")]),
        ("export type * from './dep';", [(1, "export *")]),
        ("export * as named from './dep';", []),
        ("export { dep } from './dep';", []),
    ],
)
def test_star_re_export_is_restricted_and_named_forms_are_not(
    tmp_path: Path, source: str, expected: list[tuple[int, str]]
) -> None:
    assert _forms(tmp_path, source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("declare global { interface Window { x: number } }\nexport {};", [(1, "declare global")]),
        (
            "declare module 'virtual' { export const y: number }\nexport {};",
            [(1, "declare module")],
        ),
        ("declare namespace Local { const y: number }\nexport {};", []),
    ],
)
def test_ambient_declarations_are_restricted_outside_a_declaration_file(
    tmp_path: Path, source: str, expected: list[tuple[int, str]]
) -> None:
    assert _forms(tmp_path, source) == expected


def test_a_declaration_file_may_declare_ambient_modules(tmp_path: Path) -> None:
    source = (
        "declare global { interface Window { x: number } }\ndeclare module 'virtual' {}\nexport {};"
    )
    assert _forms(tmp_path, source, name="types.d.ts") == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "import { dep } from './dep';\nObject.defineProperty(dep, 'a', { value: 2 });",
            [(2, "runtime rewrite of import")],
        ),
        (
            "import { dep } from './dep';\nObject.setPrototypeOf(dep, null);",
            [(2, "runtime rewrite of import")],
        ),
        (
            "import { dep } from './dep';\nReflect.set(dep, 'a', 2);",
            [(2, "runtime rewrite of import")],
        ),
        (
            "import * as ns from './dep';\nObject.assign(ns.dep, { a: 2 });",
            [(2, "runtime rewrite of import")],
        ),
        (
            "import { Kind } from './dep';\nKind.prototype.m = () => 1;",
            [(2, "runtime rewrite of import")],
        ),
        (
            "import { Kind } from './dep';\ndelete Kind.prototype.m;",
            [(2, "runtime rewrite of import")],
        ),
        (
            "import { dep } from './dep';\n(dep as { prototype: { z: number } }).prototype.z = 3;",
            [(2, "runtime rewrite of import")],
        ),
        # Not an import: a global, a local, or a copy handed to `Object.assign`.
        ("Object.defineProperty(window, 'x', { value: 1 });", []),
        ("Element.prototype.focus = () => undefined;", []),
        ("const local = { a: 1 };\nObject.defineProperty(local, 'a', { value: 2 });", []),
        ("import { dep } from './dep';\nexport const copy = Object.assign({}, dep);", []),
    ],
)
def test_a_runtime_rewrite_of_an_imported_object_is_restricted(
    tmp_path: Path, source: str, expected: list[tuple[int, str]]
) -> None:
    assert _forms(tmp_path, source) == expected
