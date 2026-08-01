"""Command-line interface for fatta."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from . import pairs as pairs_mod
from . import sources
from . import surprisal as surprisal_mod
from . import testhealth as testhealth_mod
from . import testmap as testmap_mod
from . import rustdoc
from . import server
from . import tsgraph
from .graph import Footprint, Graph


# -- shared ---------------------------------------------------------------------


def load_crate(
    doc_path: Path,
    include_docs: bool,
    src_root: Path | None = None,
    use_directed: bool = True,
) -> tuple[str, Graph]:
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    if doc.get("format") == tsgraph.FORMAT:
        graph = tsgraph.parse(doc, use_directed=use_directed)
        return graph.name, graph
    version = doc.get("format_version")
    if version is not None and version < 55:
        print(
            f"warning: {doc_path.name} has rustdoc format {version}, older than what"
            " the tool was tested against",
            file=sys.stderr,
        )
    root = sources.locate(doc, doc_path, src_root)
    crate = rustdoc.load(
        doc, src_root=root, include_docs=include_docs, use_directed=use_directed
    )
    if not crate.body_text(next(iter(crate.local_functions()), "")):
        print(
            f"warning: no source text found under {root} — pass --src-root",
            file=sys.stderr,
        )
    return sources.crate_name(doc), crate


def footprints_of(crate: Graph) -> list[Footprint]:
    return sorted(
        (crate.footprint(item_id) for item_id in crate.local_functions()),
        key=lambda row: -row.cf,
    )


# -- scan -----------------------------------------------------------------------


def print_table(rows: list[Footprint], limit: int) -> None:
    header = (
        f"{'function':<26}{'LOC':>5}{'body':>7}{'closure':>10}{'CF':>7}"
        "   heaviest dependencies"
    )
    print(header)
    print("-" * len(header))
    for row in rows[:limit] if limit else rows:
        deps = ", ".join(f"{name}:{tokens}" for name, tokens in row.charged[:4])
        print(
            f"{row.name:<26}{row.loc:>5}{row.body_tokens:>7}"
            f"{row.closure_tokens:>10}{row.cf:>7}   {deps}"
        )
    if limit and len(rows) > limit:
        print(f"... {len(rows) - limit} more (run without --top for all)")


def write_csv(rows: list[Footprint], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["name", "item_id", "loc", "body_tokens", "closure_tokens", "cf", "n_deps"]
        )
        for row in rows:
            writer.writerow(
                [
                    row.name,
                    row.item_id,
                    row.loc,
                    row.body_tokens,
                    row.closure_tokens,
                    row.cf,
                    len(row.charged),
                ]
            )


def cmd_scan(args: argparse.Namespace) -> int:
    name, crate = load_crate(
        args.doc, not args.no_docs, args.src_root, not args.whole_types
    )
    weighing = None
    if args.surprisal:
        weighing = surprisal_mod.Weighing(
            predictor=surprisal_mod.ollama(args.surprisal),
            crate_name=name,
            cache_path=args.surprisal_cache,
        )
        crate.weigh = weighing.weight

    rows = footprints_of(crate)
    if weighing is not None:
        weighing.save()
        if weighing.failures:
            print(
                f"warning: {weighing.failures} contracts could not be weighed and count"
                " at full weight — is Ollama running?",
                file=sys.stderr,
            )
    if not rows:
        print("no local functions found in the input", file=sys.stderr)
        return 1
    print_table(rows, args.top)
    if args.csv:
        write_csv(rows, args.csv)
        print(f"\nwrote {len(rows)} rows to {args.csv}")
    return 0


# -- pairs ----------------------------------------------------------------------


def round_robin(buckets: list[list], total: int) -> list:
    """Takes one at a time from each bucket to keep the crate distribution even."""
    out: list = []
    index = 0
    while len(out) < total and any(len(b) > index for b in buckets):
        for bucket in buckets:
            if len(out) == total:
                break
            if len(bucket) > index:
                out.append(bucket[index])
        index += 1
    return out


def cmd_pairs(args: argparse.Namespace) -> int:
    n_disagree = args.n - args.controls
    if n_disagree < 1:
        print("--n must be larger than --controls", file=sys.stderr)
        return 1

    loaded: dict[str, Graph] = {}
    disagree_buckets: list[list[pairs_mod.Pair]] = []
    agree_buckets: list[list[pairs_mod.Pair]] = []

    for doc_path in args.docs:
        name, crate = load_crate(
            doc_path, not args.no_docs, None, not args.whole_types
        )
        loaded[name] = crate
        selected = pairs_mod.select(
            name, footprints_of(crate), n_disagree, args.controls
        )
        disagree_buckets.append([p for p in selected if p.disagrees])
        agree_buckets.append([p for p in selected if not p.disagrees])

    chosen = round_robin(disagree_buckets, n_disagree)
    chosen += round_robin(agree_buckets, args.controls)
    if not chosen:
        print("no usable pairs found in the input", file=sys.stderr)
        return 1

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    numbered = list(enumerate(chosen, start=1))

    for number, pair in numbered:
        target = out / f"pair-{number:02d}.md"
        target.write_text(
            pairs_mod.render_pair(loaded[pair.crate], pair, number), encoding="utf-8"
        )

    (out / "review-sheet.md").write_text(
        pairs_mod.render_sheet(numbered), encoding="utf-8"
    )
    (out / "facit.json").write_text(
        json.dumps(
            [pairs_mod.key_entry(n, p) for n, p in numbered],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    n_dis = sum(1 for _, p in numbered if p.disagrees)
    print(f"wrote {len(numbered)} pairs to {out}")
    print(f"  {n_dis} disagreeing, {len(numbered) - n_dis} control pairs")
    print(f"  crates: {', '.join(sorted({p.crate for _, p in numbered}))}")
    print(f"\nStart with {out / 'review-sheet.md'}.")
    return 0


# -- score ----------------------------------------------------------------------

ANSWER_ROW = re.compile(r"^\|\s*(\d+)\s*\|[^|]*\|\s*([ABab])\s*\|")


def parse_answers(raw: str) -> dict[int, str]:
    """Accepts either a filled-in review sheet or a string like 'ABBA'.

    The letter parsing requires the *entire* input to be A, B and separators. Otherwise
    an empty sheet would fall through and have answers picked out of the prose — a score
    with no reviewer.
    """
    rows = {
        int(m.group(1)): m.group(2).upper()
        for m in (ANSWER_ROW.match(line) for line in raw.splitlines())
        if m
    }
    if rows:
        return rows
    letters = re.sub(r"[\s,;]", "", raw).upper()
    if letters and set(letters) <= {"A", "B"}:
        return {i: c for i, c in enumerate(letters, start=1)}
    return {}


def cmd_score(args: argparse.Namespace) -> int:
    key = json.loads(args.facit.read_text(encoding="utf-8"))
    source = Path(args.answers)
    raw = source.read_text(encoding="utf-8") if source.is_file() else args.answers
    answers = parse_answers(raw)
    if not answers:
        print("could not read any answers", file=sys.stderr)
        return 1

    tally = {
        "oenigt": {"n": 0, "cf": 0, "loc": 0},
        "kontroll": {"n": 0, "cf": 0, "loc": 0},
    }
    missing = []
    for entry in key:
        given = answers.get(entry["par"])
        if given is None:
            missing.append(entry["par"])
            continue
        bucket = tally["oenigt" if entry["oenigt"] else "kontroll"]
        bucket["n"] += 1
        bucket["cf"] += given == entry["svar_cf"]
        bucket["loc"] += given == entry["svar_loc"]

    if missing:
        print(f"unanswered pairs: {', '.join(str(p) for p in missing)}\n", file=sys.stderr)

    for label, bucket in tally.items():
        if not bucket["n"]:
            continue
        print(
            f"{label:<10} {bucket['n']:>2} pairs   "
            f"CF {bucket['cf']}/{bucket['n']}   line count {bucket['loc']}/{bucket['n']}"
        )

    dis = tally["oenigt"]
    if dis["n"]:
        print(
            f"\nOn the disagreeing pairs you agreed with CF in {dis['cf']} of {dis['n']} cases."
            "\nThat is the only number separating the metrics — the control pairs exist"
            "\nonly to show the answers are not random."
        )
    return 0


# -- argparse -------------------------------------------------------------------


DEFAULT_INDEX = Path(".fatta/graph.json")


def cmd_index(args: argparse.Namespace) -> int:
    """Builds the index for a TypeScript project at the conventional location."""
    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        tsgraph.emit(args.tsconfig, out)
    except (RuntimeError, FileNotFoundError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    graph = tsgraph.load(out)
    local = sum(1 for i in graph.items.values() if i.external is None)
    print(f"{out}: {len(graph.items)} items, {local} of them local")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    """The same answer as the MCP tool, but on the command line.

    Exists so the index can be used without the MCP transport — among other things in
    A/B measurements, where the transport would otherwise become a variable that does
    not belong."""
    doc = args.doc or DEFAULT_INDEX
    if not doc.is_file():
        print(f"no index at {doc}", file=sys.stderr)
        return 1
    _, graph = load_crate(doc, include_docs=True)
    answer = server.what_must_i_know(graph, args.symbol)
    print(answer.as_json())
    return 0 if "error" not in answer.payload else 1


DEFAULT_TESTMAP = Path(".fatta/testmap.json")


def cmd_testmap(args: argparse.Namespace) -> int:
    """Builds the test map for a TypeScript project."""
    try:
        testmap_mod.emit(args.tsconfig, args.out)
    except (RuntimeError, FileNotFoundError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    tm = testmap_mod.load(args.out)
    exercised = len({t2["name"] for t in tm.tests for t2 in t.targets})
    print(f"{args.out}: {len(tm.tests)} tests, {exercised} symbols pinned")
    return 0


def cmd_tests(args: argparse.Namespace) -> int:
    """Which tests pin a symbol, and what do they claim?"""
    path = args.map or DEFAULT_TESTMAP
    if not path.is_file():
        print(f"no test map at {path}. Build one: fatta testmap <tsconfig>", file=sys.stderr)
        return 1
    tm = testmap_mod.load(path)
    found = tm.pinning(args.symbol, args.file)
    print(testmap_mod.render(args.symbol, found, tm.mocks))
    return 0 if found else 1


def cmd_testhealth(args: argparse.Namespace) -> int:
    """The cleanup queue: tests pinning states production cannot produce."""
    map_path = args.map or DEFAULT_TESTMAP
    if not map_path.is_file():
        print(f"no test map at {map_path}", file=sys.stderr)
        return 1
    tm = testmap_mod.load(map_path)
    graph = None
    graph_path = args.graph or DEFAULT_INDEX
    if graph_path.is_file():
        _, graph = load_crate(graph_path, include_docs=True)
    else:
        print("note: no graph found — the waterline signal is omitted", file=sys.stderr)
    findings = testhealth_mod.analyze(tm, graph)
    print(testhealth_mod.render(findings, args.limit if args.limit else len(findings)))
    churn = testhealth_mod.measure_churn(tm, args.repo)
    if churn:
        print()
        print(testhealth_mod.render_churn(churn, findings))
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    """Local GUI over the same dispatch as the MCP server."""
    from . import gui as gui_mod

    doc = args.doc or DEFAULT_INDEX
    if not doc.is_file():
        print(
            f"no index at {doc}. Build one with: fatta index <tsconfig.json>",
            file=sys.stderr,
        )
        return 1
    _, graph = load_crate(doc, include_docs=True)
    tmap = None
    tmap_path = args.testmap or DEFAULT_TESTMAP
    if tmap_path.is_file():
        tmap = testmap_mod.load(tmap_path)
    gui_mod.serve_gui(
        graph, tmap=tmap, port=args.port, repo=str(args.repo), open_browser=not args.no_open
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    doc = args.doc or DEFAULT_INDEX
    if not doc.is_file():
        print(
            f"no index at {doc}. Build one with: fatta index <tsconfig.json>",
            file=sys.stderr,
        )
        return 1
    _, graph = load_crate(doc, include_docs=True, src_root=args.src_root)
    tmap = None
    tmap_path = args.testmap or DEFAULT_TESTMAP
    if tmap_path.is_file():
        tmap = testmap_mod.load(tmap_path)
    server.serve(graph, tmap=tmap)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fatta",
        description="Comprehension footprint (CF) and test maps for codebases.",
        epilog=(
            "Generate Rust input with: cargo rustdoc --lib -- -Zunstable-options "
            "--output-format json --document-private-items (requires nightly)"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="measure and rank a crate or graph")
    scan.add_argument("doc", type=Path, help="path to <crate>.json from rustdoc, or a fatta graph")
    scan.add_argument("--src-root", type=Path, help="root for relative span paths")
    scan.add_argument("--csv", type=Path, help="write the result as CSV")
    scan.add_argument("--top", type=int, default=0, help="show only the N largest")
    scan.add_argument(
        "--no-docs", action="store_true", help="do not count docs as part of the contract"
    )
    scan.add_argument(
        "--whole-types",
        action="store_true",
        help="charge whole type definitions instead of only the members used",
    )
    scan.add_argument(
        "--surprisal",
        metavar="MODEL",
        help=(
            "weigh contracts by how unexpected they are, via a local Ollama model"
            " (e.g. qwen2.5-coder:14b)"
        ),
    )
    scan.add_argument(
        "--surprisal-cache",
        type=Path,
        default=Path(".fatta-surprisal.json"),
        help="where weights are cached between runs",
    )
    scan.set_defaults(func=cmd_scan)

    pair = sub.add_parser("pairs", help="build a blind review pack")
    pair.add_argument("docs", type=Path, nargs="+", help="one or more <crate>.json")
    pair.add_argument(
        "--out", type=Path, default=Path("review"), help="directory to write to"
    )
    pair.add_argument("--n", type=int, default=12, help="total number of pairs")
    pair.add_argument(
        "--controls", type=int, default=3, help="how many of them are control pairs"
    )
    pair.add_argument(
        "--no-docs", action="store_true", help="do not count docs as part of the contract"
    )
    pair.add_argument(
        "--whole-types",
        action="store_true",
        help="charge whole type definitions instead of only the members used",
    )
    pair.set_defaults(func=cmd_pairs)

    score = sub.add_parser("score", help="compare filled-in answers against the key")
    score.add_argument("facit", type=Path, help="facit.json from pairs")
    score.add_argument(
        "answers", help="a filled-in review sheet, or a string like ABBA"
    )
    score.set_defaults(func=cmd_score)

    index = sub.add_parser("index", help="build the index for a TypeScript project")
    index.add_argument("tsconfig", type=Path, help="path to tsconfig.json")
    index.add_argument("--out", type=Path, default=DEFAULT_INDEX)
    index.set_defaults(func=cmd_index)

    ask = sub.add_parser("ask", help="ask the index what one must know about a symbol")
    ask.add_argument("symbol", help="the function's name")
    ask.add_argument("doc", type=Path, nargs="?", help=f"index (default: {DEFAULT_INDEX})")
    ask.set_defaults(func=cmd_ask)

    tmap = sub.add_parser("testmap", help="build the test map for a TypeScript project")
    tmap.add_argument("tsconfig", type=Path)
    tmap.add_argument("--out", type=Path, default=DEFAULT_TESTMAP)
    tmap.set_defaults(func=cmd_testmap)

    tq = sub.add_parser("tests", help="which tests pin a symbol, and what do they claim")
    tq.add_argument("symbol")
    tq.add_argument("--map", type=Path, help=f"test map (default: {DEFAULT_TESTMAP})")
    tq.add_argument("--file", help="filter by the symbol's file path (on name clashes)")
    tq.set_defaults(func=cmd_tests)

    th = sub.add_parser("testhealth", help="tests pinning unreachable states, ranked")
    th.add_argument("--map", type=Path, help=f"test map (default: {DEFAULT_TESTMAP})")
    th.add_argument("--graph", type=Path, help=f"graph for the waterline (default: {DEFAULT_INDEX})")
    th.add_argument("--limit", type=int, default=25)
    th.add_argument("--repo", type=Path, default=Path("."), help="git repo for churn history")
    th.set_defaults(func=cmd_testhealth)

    gui = sub.add_parser("gui", help="local GUI over the same operations as the MCP server")
    gui.add_argument("doc", type=Path, nargs="?", help=f"index (default: {DEFAULT_INDEX})")
    gui.add_argument("--testmap", type=Path, help=f"test map (default: {DEFAULT_TESTMAP})")
    gui.add_argument("--port", type=int, default=4715)
    gui.add_argument("--repo", type=Path, default=Path("."), help="git repo for churn")
    gui.add_argument("--no-open", action="store_true", help="do not open the browser")
    gui.set_defaults(func=cmd_gui)

    serve = sub.add_parser("serve", help="run the MCP server over an index")
    serve.add_argument(
        "doc",
        type=Path,
        nargs="?",
        help=f"index to serve (default: {DEFAULT_INDEX} in the working directory)",
    )
    serve.add_argument("--src-root", type=Path, help="root for relative span paths")
    serve.add_argument("--testmap", type=Path, help=f"test map (default: {DEFAULT_TESTMAP})")
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
