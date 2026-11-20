# meizel/ — Restricted TypeScript

The TypeScript counterpart of [restricted Python](restricted.md): the forms that leave a dependency
or a name to the run instead of the source, so a static scan cannot see what the file depends on.
They are reported as `restricted-typescript`, which is recorded as debt like `restricted-python`:
the key is `file#form` (with the form's detail), it belongs to the directory of the file, and the
baseline lives in `[debt.restricted-typescript]` of that directory's `meizel.toml`.

Every form is found from the compiler's symbols, never from text: a local variable called `eval`
or `window` is not the global, and a string that contains `eval(` is not a call. The forms are
judged in the files `[typescript].scopes` selects, tests included, except the computed `import()` /
`require()`, which are judged in every file the run scans.

## Forms

| form | what it is | exempt with |
|---|---|---|
| `import()` / `require()` `'computed target'` | a dynamic import or an unshadowed `require` whose specifier is not a string the source states | `[loads]`, `[external]` |
| `eval of source text` | the global `eval`, in any use (`eval(s)`, `(0, eval)(s)`, `const run = eval`, `globalThis.eval(s)`); not `typeof eval`, not a property called `eval` | `[external]` |
| `Function constructor` | calling or constructing the global `Function` (`new Function(...)`, `Function(...)`, `globalThis.Function(...)`); not `Function` as a type or in `instanceof` | `[external]` |
| `dynamic global key` | `globalThis[key]`, `window[key]`, `self[key]` or `global[key]` where the type of `key` is not a string or number literal, or a union of them. `"name"`, a `const` bound to a literal, and `"a" \| "b"` state the key; `string` and a template type do not. A key whose type the compiler cannot resolve is not stated | `[dynamic-attrs]` |
| `export *` | `export * from "x"` (and `export type * from`). Name what is re-exported. `export * as ns from "x"` and `export { a } from "x"` are named and are not reported | none |
| `declare global` / `declare module` | an ambient `declare global { }` or `declare module "x" { }` in a file that is not a declaration file (`.d.ts`); move it into one | none |
| `runtime rewrite of import` | a call that rewrites an object an `import` bound: the first argument of `Object.defineProperty`, `defineProperties`, `setPrototypeOf`, `assign`, `Reflect.defineProperty`, `set`, `setPrototypeOf`, `deleteProperty`; or an assignment, `delete` or `++` through the `prototype` or `__proto__` of an imported name (`Kind.prototype.m = f`) | none |

`as any` and `@ts-ignore` are not part of this subset: they are the business of `tsc` in strict mode
and of the linter.

## Declarations

`[external]` and `[dynamic-attrs]` work as for Python ([restricted Python](restricted.md)): the file
is listed in its directory's `meizel.toml` with a reason, and the same site is listed in
`meizel.policy.toml`; an entry whose file has none of the forms it exempts is `stale-external` or
`stale-dynamic-attrs`. `[external]` exempts the forms that run code from outside the repository
(`import()`, `require()`, `eval`, `Function`); `[dynamic-attrs]` exempts `dynamic global key`, the
file that owns a global name only the run knows. A file listed under `[loads]` is exempt from every
restricted form, and a file that only loads, loads. The three forms with no declaration are repaired
or recorded as debt.

## Not covered

- Rewriting a **global** rather than an import: `Object.defineProperty(window, ...)`,
  `Element.prototype.m = ...`, `document.x = ...`. Test setup does this routinely, and the object is
  not part of the repository's dependency graph; the form above is about what an `import` names.
- Code strings through the timers (`setTimeout("code")`). `Function` is judged where the source
  calls or constructs it by name: `const F = Function; F("code")`, `(function () {}).constructor("code")`
  and other ways to reach it without naming it are not found, which is less than `eval`, judged in any
  use. Also not found: `Reflect.get(globalThis, key)`, and a computed key
  on any other object.
- Whether a literal-typed key is the right one: the compiler's type is the source's statement.

Parent: [the checker](../checker.md).
