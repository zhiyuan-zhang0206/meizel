# meizel/ — Purity and Bounded Container Budgets

## Why mechanical purity and container budgets

The goal is understandable, changeable code and trustworthy feedback. Bounded interfaces
and explicit effects can help, but passing the checks does not establish cohesive design.
Review actual owners, consumers and assertions; avoid forwarding layers or callback bags
created only to satisfy a budget.

## What the evidence means

A successful `check`, including `strict`, means the implemented checks passed for the
reported scope. It is not a semantic purity proof or a test-resource assessment. A path
filter or `--changed` does not turn that scoped result into a whole-repository judgment.

| Dimension | Evidence and limit |
|---|---|
| Recognized syntax | `impure-call` and related diagnostics name matched imports, calls or writes. An import or async declaration is an observation, not execution. A name for an impure call, not called (`_is_file = Path.is_file`), is that call. `resolve`, `glob`, `open` and the other I/O methods count on any receiver (`self.resolve()` too); `replace` only on a path: annotated, built by `Path(...)`, looped over `iterdir`/`glob`/`rglob`, or `self.x` of those. |
| Unresolved or unmeasured behavior | Unresolved imports/patches are reported where recognized. No diagnostic does not establish absence of callback effects, input mutation or transitive effects. |
| Structure | Container budgets and frozen-shape rules bound forms and sizes, not semantic effects: a frozen dataclass can contain a mutable list, and a frozen JS holder or Set does not stop nested mutation. |
| Test resources | Fixture diagnostics recognize configured requests. They do not measure bootstrap cost or authorize a lightweight runner. [Static ownership and refusal canaries](../../../tests/fixtures/docs/static-environment.md) govern it. |

Passing observed values can separate decisions from effects. Injecting a callable makes
its operation explicit but does not remove its effects. Use [explain source evidence](explain.md) to trace
owners and bounded observations, then verify behavior at the actual boundary.

## Three purity modes

A manifest declares purity either for the whole directory (`purity = "strict"`) or per direct
child under `[purity]`, with `"."` as the directory default:

```toml
[purity]
"." = "ratchet"
"model.py" = "strict"
"scopes.py" = "strict"
```

Every Python or TypeScript file resolves to its nearest enclosing declaration (`off` by default):

- **`off`**: only locality and patch-recording rules apply. A manifest that names it writes
  `{ mode = "off", why = "..." }`: an effect shell whose pure decisions are extracted and reviewed.
  A file no manifest mentions is `off`; the bare string `"off"` is refused (`manifest-syntax`).
- **`ratchet`**: all 15 purity and container-budget rules are evaluated. Existing
  violations may be recorded in `[debt.<code>]` via `python -m meizel debt record` and can
  only shrink (`debt-paid` fires when a recorded violation is fixed, and also when a
  `ratchet` file or directory reaches zero remaining purity violations so it must be
  promoted to `strict`).
- **`strict`**: all 15 purity and container-budget rules are hard errors and cannot be
  recorded as debt.

Test files (`tests/**`, `test_*.py`, `*_test.py`, `conftest.py`) do not inherit a parent
directory's module-level `strict` or `ratchet` mode for production-code rules, unless
explicitly targeted. Instead, a test file whose first-party targets are all `strict` or
`ratchet` is judged by the test-purity rules (`impure-test-fixture` and
`nested-patch-target`) at the strictest shared mode (`ratchet` if any target is
`ratchet`, otherwise `strict`).

## The 15 rules

| Code | Scope | What it catches |
|---|---|---|
| `impure-edge` | `strict`, `ratchet` module | Importing or reading an attribute from a first-party module whose effective purity is `off` |
| `impure-call` | `strict`, `ratchet` module | `async def`, `global`, `nonlocal`, importing an impure standard library module (from complete `sys.stdlib_module_names` classification), importing any third-party package not listed in `pure-third-party` (fail-closed), or calling an ambient clock, randomness, environment, I/O or filesystem method (`time.*`, `datetime.now`, `os.environ`, `random.*`, `uuid.uuid4`, `open`, the `os` file and descriptor calls, `Path` I/O methods; list: `DEFAULT_IMPURE_CALLS` plus policy `impure-calls`; a call the file's `[roots]` licenses is exempt) |
| `unfrozen-value` | `strict`, `ratchet` module | A class that is not an Enum, Exception, Protocol, TypedDict, NamedTuple, frozen `BaseModel`, or `@dataclass(frozen=True)`, or a module-level mutable literal/comprehension/call assigned to a binding |
| `untyped-export` | `strict`, `ratchet` module | A public function (or exported symbol) missing parameter or return type annotations, or annotated with `Any` or bare `dict` |
| `pass-through-function` | `strict`, `ratchet` module | A public undecorated function whose body only forwards its exact parameters to another function or module attribute call |
| `nested-attr-write` | `strict`, `ratchet` module | Mutating state through a chained attribute (`a.b.c = x` or `self.a.b = x`, depth $\ge 2$) |
| `domain-subset-leak` | `strict`, `ratchet` module | Branching on the same multi-member Enum subset (`x in {E.A, E.B}` or `case E.A \| E.B:`) across 2 or more non-test modules instead of a predicate on the Enum |
| `stale-export` | `strict`, `ratchet` export | An entry in `exports` of a subpackage `meizel.toml` that no external fact edge traverses |
| `wide-exports` | `strict`, `ratchet` manifest | A subpackage `meizel.toml` exporting more than `max-exports` children (default 4) |
| `wide-fanout` | `strict`, `ratchet` child | A `[uses]` entry depending on more than `max-uses` sibling targets (default 8) |
| `wide-public-surface` | `strict`, `ratchet` module | A module defining more than `max-public-symbols` public behavioral symbols (default 6; frozen values, Enums, Protocols, TypedDicts, NamedTuples and Exceptions do not count) |
| `wide-params` | `strict`, `ratchet` module | A function or method taking more than `max-params` parameters excluding `self`/`cls` (default 6) |
| `deep-attr-chain` | `strict`, `ratchet` module | An expression chaining more than `max-attr-hops` non-module attribute accesses (`a.b.c.d`, default 3) |
| `impure-test-fixture` | test of `strict` / `ratchet` | Requesting `monkeypatch`, or any fixture transitively inferred impure via AST taint graph analysis (connecting to runtime infrastructure, async fixtures, impure stdlib/third-party imports, ambient reads) plus optional policy `impure-fixtures` when all first-party targets under test are `strict` or `ratchet` |
| `nested-patch-target` | test of `strict` / `ratchet` | Patching through a multi-hop attribute chain (`monkeypatch.setattr(a.b, "c", ...)` or dotted string with $\ge 2$ attribute hops) |

## Policy configuration

Repository-specific additions and container budget thresholds live under `[purity]` in
[meizel.policy.toml](policy/policy.md):

```toml
[purity]
pure-third-party = ["pydantic", "dotenv", "feedparser", "loguru", "mcp", "yaml"]
impure-calls = ["logging.info", "logging.error"]
impure-fixtures = []
max-uses = 8
max-exports = 4
max-public-symbols = 6
max-params = 6
max-attr-hops = 3
```

Parent: [the checker](checker.md).
