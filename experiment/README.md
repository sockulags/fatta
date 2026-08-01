# The twin experiment

The same todo backend built twice, to turn an architecture claim into a number:
**is a uniform structure cheaper to understand than a layered one?**

- `conformance/` — the contract and the suite both must pass. Shared types, shared rules,
  shared tests.
- `layered/` — the conventional enterprise stack: api over service over repository, with
  a distinct type family per level (rows, entities, transport objects) and mappers in
  between.
- `uniform/` — a single node type. Lists are nodes, todos are nodes, subtasks are nodes.
  The operations are recursive functions over nodes.

Both store in SQLite and depend on exactly the same crates. The difference between them is
the structure and nothing else — that is the whole point of the shared conformance suite:
if both pass it they are functionally interchangeable, and only the shape differs.

## The domain

Enough structure for layering to cost something, small enough to hold in your head: lists
containing todos, todos with subtasks at arbitrary depth, tags, due dates, and search
combining filters.

The load-bearing rule is recursive: **a todo may not be marked done while any descendant
is open**. It forces both implementations to walk the whole subtree, which is where the
difference between "children of the same kind" and "a new kind of thing per level"
actually shows.

## Building

Requires a C compiler because `rusqlite` builds SQLite from source. The one that ships
with rustup's gnu toolchain is not enough — it can only link. On this machine a usable one
lives in WinLibs:

```bash
export PATH="/c/Users/lucas/AppData/Local/Microsoft/WinGet/Packages/BrechtSanders.WinLibs.POSIX.MSVCRT_Microsoft.Winget.Source_8wekyb3d8bbwe/mingw64/bin:$PATH"
cargo test
```

## Measuring

```bash
cargo rustdoc -p layered -- -Zunstable-options --output-format json --document-private-items
cargo rustdoc -p uniform -- -Zunstable-options --output-format json --document-private-items
uv run fatta scan experiment/target/doc/layered.json --src-root experiment
```

Spans in a workspace are relative to the workspace root, not the package — hence
`--src-root experiment`.

## Outcome (2026-08-01)

Paired per operation, i.e. the same behavior compared against itself. Body is the
function's own text, closure is what must be read beyond it. The layered variant splits
several operations across the api and service levels, so all functions sharing a name are
summed.

| operation | layered body | layered closure | uniform body | uniform closure |
|---|---|---|---|---|
| create_list | 176 | 895 | 50 | 148 |
| add | 281 | 797 | 256 | 273 |
| complete | 154 | 425 | 122 | 194 |
| reopen | 69 | 327 | 49 | 101 |
| tag | 74 | 340 | 51 | 106 |
| move_under | 268 | 542 | 192 | 154 |
| tree | 170 | 452 | 59 | 60 |
| search | 232 | 511 | 158 | 110 |
| **total** | **1424** | **4289** | **937** | **1146** |

The bodies differ by 1.5×. **The closures differ by 3.7×.** The difference sits not in how
much code was written but in how much else you must know to read it.

### Correction (2026-08-01, later the same day)

The first report said 9.6×, and that the uniform closure was constant across operations.
Both rested on a model that only followed dependencies through **signatures** and ignored
what the body calls. That failed visibly in TypeScript — a React component takes no
parameters and thus appeared to have no dependencies at all — but it was equally wrong in
Rust, just less visibly, because Rust signatures carry more.

With calls included the direction stands but the magnitude more than halves, and the
constancy disappears: it was an artifact of the model not seeing what the code did.

An asymmetry worth knowing: the TypeScript frontend resolves calls with tsc's type
checker, while the Rust frontend matches names against the source text because rustdoc
JSON has no bodies. Name matching overestimates, and probably most in the layered variant,
which has more distinct names. A few tenths of the ratio above is likely that effect
rather than structure.

## Why the number should not be over-read

**n = 1, and the same author wrote both.** I knew the hypothesis while writing. That the
layered variant unconsciously grew heavier cannot be ruled out. Against it: both pass
identical tests, median LOC is 6 in both, and the bodies differ only 1.5× — had I simply
written more code in one, that gap would be larger.

**CF is still an untested proxy.** The metric has never been shown to predict that a model
actually fails. This measures closure size, not difficulty. (The later A/B/C experiment in
`ab/RESULTS.md` confirmed the caution: CF did not predict outcomes.)

**The uniform variant concentrates complexity.** Its heaviest function, `store::load` at
482, is worse than the layered variant's worst at 308 — but from body length, not closure.

**And most seriously: CF does not see what was given up.** The uniform variant discarded
static guarantees — `done` is the string `"1"` — and that lowers the closure at no cost in
the metric. Optimize CF directly and the degenerate solution is `fn do(x: &str) -> String`
everywhere, closure zero. **CF rewards exactly what makes verification harder**, and must
therefore never become an optimization target without a counterweight measuring
guarantees.

## What is visible without measuring

The uniform variant pays its price in `store.rs`: with attributes as rows rather than
columns, the schema stops carrying meaning and the compiler stops checking it. `done` is
the string `"1"`, not a bool. That is exactly the predicted trade — uniformity is bought
with static guarantees — and it shows here in miniature before anything larger is built on
top of it.
