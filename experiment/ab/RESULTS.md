# The A/B/C experiment: results

Ten functions in **p1** (a production Next.js/TypeScript app, ~26k lines, 171 test files,
pinned at a fixed commit in an isolated clone), body emptied, judge tests hidden, three
arms: **A** baseline (Read/Grep), **B** the fatta index, **C** a graphify knowledge graph.
Outcome = run the full suite including the judge. Raw data in `results-p1.json`.

## The numbers

| arm | green | total tokens | files read |
|---|---|---|---|
| A — baseline | 3/10 | 820,429 | 118 |
| B — fatta | 3/10 | 797,529 (−2.8%) | 111 |
| C — graphify | 3/10 | 764,057 (−6.9%) | 135 |

## Finding 1: the outcome is a property of the case, not the tool

**10 of 10 cases were concordant** — all three arms succeeded or failed together, every
time. The same three cases green, the same seven red, usually on exactly the same judge
file. The tool did not change correctness in a single case.

What decided instead was whether the specification could be recovered from what was
visible: the green cases are fully determined by surrounding code and non-judge tests; the
red ones pin literals or behaviors that exist **only in the hidden judge test** (exact
error messages, exact call shapes, busy-guard semantics).

## Finding 2: the token savings are small

−3 to −7%, with per-case variance larger than the between-arm differences. The −12%
measured in the v1 design was largely an artifact of forbidding test reading — once the
agent may use tests as spec, which is the realistic workflow, the indexes' edge shrinks to
noise level. A modern agent greps its way to orientation almost as cheaply as it looks it
up.

## Finding 3: CF did not predict the outcome

Green: CF 352, 505, 1060. Red: CF 283, 416, 626, 754, 1691, 3318, 10492. Red cases occur
across the whole range, including below the greens. Outcomes were governed by spec
recoverability, which is orthogonal to the comprehension footprint. CF measures the cost
of *reading in* — not the probability of *succeeding*, at least not in the regeneration
task.

## Conclusion

In a well-tested codebase, the bottleneck for an agent is not finding or understanding the
code — the baseline does that almost as cheaply as either index. The bottleneck is
**behavioral specification, and it lives in the tests**. Three independent tool arms with
identical outcomes is strong evidence.

The practical product of this is therefore not a comprehension index but a **test map**:
function → the tests that pin its behavior. Graphify already has the edges (tests import
functions); fatta has the closure. The combination — "to change X, first read these N
tests" — attacks what actually felled 21 of 30 runs.

## Known weaknesses

- n = 10 in a single codebase, one model, one prompt per arm.
- Cases 1–2 ran before two leaks were plugged (the fatta index carried function bodies;
  a metadata file pointed at the judge). No agent exploited them — the outcomes were red —
  but conditions differed.
- Hiding the judge makes cases with judge-exclusive literals impossible by construction;
  binary pass/fail therefore underestimates how close the implementations came. Per-run
  test counts are logged from case 4 onward.
