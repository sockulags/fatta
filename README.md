# fatta

*Swedish for "to grasp, to understand".*

A **comprehension index** for a codebase: for every function, the minimal closed set you
must understand to change it — computed from the compiler's own type information — plus a
**test map** that answers the question that actually decides whether a change is safe:
which tests pin this function's behavior, and what exactly do they assert?

Two uses of the same machinery. As a metric: the **comprehension footprint** (CF), how much
text a reader must take in, measured in tokens. As a service: an MCP server and a local GUI
that answer an AI agent (or a human) "what must I know to change this?", bounded.

The core in `graph.py` is language-neutral. Frontends build the same graph: `rustdoc.py`
for Rust from rustdoc JSON, `tsgraph.py` plus `scripts/ts-graph.mjs` for TypeScript from
tsc's own type checker.

## What CF is

Reading a function is not reading its lines. To know what it does you must also know what
its parameters and return types *are* — and to know that, you must know what those types
contain in turn. That chain is the **contract closure**.

But you do not need to read the bodies of the functions it calls. A contract — signature,
docs, fields, failure modes — should suffice. That is the entire promise of abstraction.

CF puts a number on it:

```
CF(M) = tokens(M's own body)
      + Σ tokens(contract) for everything M's signature transitively touches
```

Three choices make the metric what it is:

**Contracts, never bodies.** Dependencies' implementations are not counted. This is the
metric's load-bearing assumption, and it is deliberately falsifiable: if it turns out you
must read the bodies in practice, the abstractions leak and the metric measures the wrong
thing.

**Tokens, not lines.** The constraint being modeled is a context window, and tokens are
its unit.

**Well-known crates cost zero.** `std`, `serde`, `tokio` and the like are already known to
the reader. The metric is thus relative to prior knowledge — a feature, not a flaw. The
list sits at the top of `graph.py` and is meant to be visible rather than hidden.

### Why not just line count

The probe crate in `probes/cfprobe` makes the point with two functions:

```
function      LOC  body  closure     CF   heaviest dependencies
run             6    61      108    169   Limits:26, Report:25, Config:25
checksum       14   101        0    101
```

`run` is six lines, but its signature takes a `Config` containing a `Limits` and a
`Stage`, and returns a `Report`. All of that must be read. `checksum` is more than twice
as long, but touches only `&[u8]` and `u64` — which the reader already knows — so its
footprint is just its own body.

Line count ranks them in the opposite order. That inversion is what the metric exists to
catch.

## Using it

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and (for Rust input) a nightly
Rust toolchain.

Generate rustdoc JSON for the crate you want to measure:

```bash
cargo rustdoc --lib -- -Zunstable-options --output-format json --document-private-items
```

Run the scan:

```bash
uv run fatta scan target/doc/<crate>.json
```

Useful flags: `--no-docs` excludes doc comments from dependency contracts, `--csv FILE`
writes results for further analysis, `--top N` shortens the table, and `--src-root DIR` is
needed when the sources are not three levels above the JSON file. For crates fetched from
crates.io the source is found automatically in the registry cache.

## TypeScript

```bash
node scripts/ts-graph.mjs ../your-app/tsconfig.json your-app.json
uv run fatta scan your-app.json --top 12
```

The emitter loads `typescript` from the project being analyzed, so no version needs to be
installed here. Monorepo packages work: point it at the package's own tsconfig.

## The test map

The A/B/C experiment (`experiment/ab/RESULTS.md`) showed that what decides whether an
agent succeeds in changing a function is not code comprehension but whether the behavioral
specification can be found — and it lives in the tests, often as the only place in the
codebase. The test map makes it queryable:

```bash
fatta testmap tsconfig.json          # build .fatta/testmap.json
fatta tests processImportJobById     # which tests pin this symbol, and what do they claim?
```

The answer lists the tests with their expect lines verbatim — the exact error messages and
call shapes that cannot be guessed — plus what is mocked in each test file. An empty
answer is its own warning: the behavior is unspecified, and changing it breaks no test.

Tests reach code in three ways and the map captures all of them: resolved identifiers,
destructured dynamic imports (`const { GET } = await import('@/app/...')`), and
source-reading tests (`readFileSync('app/.../page.tsx')`). Helper functions inside the
test file are expanded, and the call graph bridges indirect hits: a test that pins the
caller pins the callee.

Validated against experimentally measured ground truth — the judge test files per case:
the top prediction is a real judge in 10 of 13 cases, and 11 of 13 cases have at least one
judge in the list. The misses are deep indirection through component trees.

### The cleanup queue: `fatta testhealth`

True unreachability is undecidable, but a test that pins a state production can never
produce has to break out of something, and the breakouts show: type casts
(`as any`/`as unknown`) at call sites of production code, source-reading tests that regex
the production file, long literals pinned on internal functions, and `@ts-expect-error`.
The waterline — the test calling an internal function directly instead of going through
the entry point — is added as context once another signal has fired: it says where the
fabricated state arose, below the validation layer.

```bash
fatta testhealth        # ranked review queue with evidence per line
```

A queue to review, not a verdict: every signal has legitimate exceptions (partial
fixtures, deliberate isolation, intentional brand/copy tests, and functions sitting at
runtime boundaries like localStorage or JSON, where untyped input is reality).

It also cross-references git history: test files repeatedly fixed in commits that did not
touch any of their production targets are pure maintenance cost, and are listed with their
counts. Monorepo packages are handled via `git rev-parse --show-prefix`.

## The index as a service

```bash
uv run fatta serve your-app.json     # MCP over stdio
uv run fatta gui                     # local GUI on http://127.0.0.1:4715
```

The MCP server exposes five tools: `what_must_i_know` (the closed set, with contracts,
provenance and cost), `which_tests_pin` (the behavioral spec, verbatim), `doc_leverage`
(where a trustworthy contract would save the most reading), `list_symbols`, and
`test_health`. The GUI's `POST /api` goes straight into the same dispatch as the MCP
server's `tools/call` — one capability surface, two transports; a tool added to the
dispatch appears in both.

What separates the answers from ordinary code search is boundedness. A search returns
relevant text with no bottom — you never know when you have seen enough. This answers
"this is everything, you can stop reading", and says so explicitly when it *cannot*: if a
package without a graph is reached, `bounded` is set to false and the missing pieces are
listed. Staying silent would pass the set off as closed when it is not, and the agent
would stop reading in the wrong place.

Every fact carries its provenance. In this version everything is `derived` — extracted
from the code and true by construction. Asserted facts that nobody checks are deliberately
absent: a fact that makes an agent stop reading must be true, or it is worse than no fact
at all.

## The blind review

Before spending money on model runs, the metric can pass a human gate: does CF rank code
the way an experienced developer's intuition ranks difficulty?

A random sample will not do, because CF and line count agree in most cases. What separates
the metrics are the pairs where they rank in **opposite** order. `fatta pairs` extracts
them, pairs them within the same crate, and renders each pair without scores — with a
randomized but deterministic A/B order, and contracts sorted alphabetically rather than by
size, so nothing leaks which function the metric points to.

```bash
bash scripts/build-corpus.sh
uv run fatta pairs corpus/target/doc/*.json --out review
```

Fill in the review sheet and evaluate:

```bash
uv run fatta score review/answer-key.json review/review-sheet.md
```

The pack also contains control pairs where the metrics agree. They exist to catch random
answering: if the controls also land around fifty-fifty, neither metric carries, and the
disagreements say nothing either.

### The measurement corpus

Four crates chosen for difference in code shape rather than popularity, versions pinned in
`corpus/Cargo.lock`:

- **semver** — parsing and comparisons, well documented; where the doc confounder hits hardest
- **serde_json** — large shared types threaded through everything; where CF should beat line count
- **memchr** — algorithmic code with almost no types of its own; negative control
- **tokio-util** — async, where the difficulty sits in lifetimes and cancellation safety
  rather than in types. Included as a predicted failure: writing down where the metric is
  expected to fail *before* measuring is the difference between a test and a rationalization.

## Status and open questions

The A/B/C experiment falsified the original core hypothesis: comprehension indexes did not
change agent correctness (10/10 concordant outcomes across three tool arms), and CF did
not predict failures. What decided outcomes was spec recoverability — hence the pivot to
the test map. Full write-up in `experiment/ab/RESULTS.md`.

**Doc comments dominate raw CF.** On `semver` v1.0.28, nearly all discrimination against
line count comes from prose in dependency doc comments. With `--no-docs` the ranking falls
back toward line count. Both variants must compete as predictors — the question cannot be
settled from the armchair.

**The module looks like the right unit.** Sibling functions share a closure, so
function-level budgets are probably too fine-grained.

**Token counting is an estimate.** `estimate_tokens` is character-based. Good enough for
ranking; swap in a real tokenizer before absolute thresholds mean anything.

**Known extraction limits.** Type references are found via a heuristic over rustdoc JSON
(objects with both `id` and `path`). Macro-generated code has no source text. Generic
bounds are counted as the trait's contract, not every impl. The rustdoc format is
unstable; built against `FORMAT_VERSION` 61. The Rust frontend resolves calls by name
matching (rustdoc JSON has no bodies), which overestimates; the TypeScript frontend
resolves them with the type checker and is the more precise of the two.

## Development

```bash
uv run pytest
```

Tests run against a checked-in fixture and need no Rust toolchain. If you change the probe
crate: `bash scripts/regen-fixture.sh`.
