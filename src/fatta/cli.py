"""Kommandoradsgränssnitt för fatta."""

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
from . import testmap as testmap_mod
from . import rustdoc
from . import server
from . import tsgraph
from .graph import Footprint, Graph


# -- gemensamt ------------------------------------------------------------------


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
            f"varning: {doc_path.name} har rustdoc-format {version}, äldre än det"
            " verktyget testats mot",
            file=sys.stderr,
        )
    root = sources.locate(doc, doc_path, src_root)
    crate = rustdoc.load(
        doc, src_root=root, include_docs=include_docs, use_directed=use_directed
    )
    if not crate.body_text(next(iter(crate.local_functions()), "")):
        print(
            f"varning: hittade ingen källtext under {root} — ange --src-root",
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
        f"{'funktion':<26}{'LOC':>5}{'kropp':>7}{'slutning':>10}{'CF':>7}"
        "   tyngsta beroenden"
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
        print(f"... {len(rows) - limit} till (kör utan --top för alla)")


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
                f"varning: {weighing.failures} kontrakt kunde inte viktas och räknas"
                " med full vikt — kör Ollama igång?",
                file=sys.stderr,
            )
    if not rows:
        print("inga lokala funktioner hittades i indata", file=sys.stderr)
        return 1
    print_table(rows, args.top)
    if args.csv:
        write_csv(rows, args.csv)
        print(f"\nskrev {len(rows)} rader till {args.csv}")
    return 0


# -- pairs ----------------------------------------------------------------------


def round_robin(buckets: list[list], total: int) -> list:
    """Plockar ett i taget från varje hink så att crate-fördelningen hålls jämn."""
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
        print("--n måste vara större än --controls", file=sys.stderr)
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
        print("hittade inga användbara par i indata", file=sys.stderr)
        return 1

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    numbered = list(enumerate(chosen, start=1))

    for number, pair in numbered:
        target = out / f"par-{number:02d}.md"
        target.write_text(
            pairs_mod.render_pair(loaded[pair.crate], pair, number), encoding="utf-8"
        )

    (out / "granskningsark.md").write_text(
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
    print(f"skrev {len(numbered)} par till {out}")
    print(f"  {n_dis} oeniga, {len(numbered) - n_dis} kontrollpar")
    print(f"  crates: {', '.join(sorted({p.crate for _, p in numbered}))}")
    print(f"\nBörja med {out / 'granskningsark.md'}.")
    return 0


# -- score ----------------------------------------------------------------------

ANSWER_ROW = re.compile(r"^\|\s*(\d+)\s*\|[^|]*\|\s*([ABab])\s*\|")


def parse_answers(raw: str) -> dict[int, str]:
    """Tar antingen ett ifyllt granskningsark eller en sträng som 'ABBA'.

    Bokstavstolkningen kräver att *hela* indata är A, B och avskiljare. Annars skulle ett
    tomt ark falla igenom och få svar uppplockade ur brödtexten — en poäng utan bedömare.
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
        print("kunde inte läsa några svar", file=sys.stderr)
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
        print(f"obesvarade par: {', '.join(str(p) for p in missing)}\n", file=sys.stderr)

    for label, bucket in tally.items():
        if not bucket["n"]:
            continue
        print(
            f"{label:<10} {bucket['n']:>2} par   "
            f"CF {bucket['cf']}/{bucket['n']}   radantal {bucket['loc']}/{bucket['n']}"
        )

    dis = tally["oenigt"]
    if dis["n"]:
        print(
            f"\nPå de oeniga paren höll du med CF i {dis['cf']} av {dis['n']} fall."
            "\nDet är den enda siffra som skiljer måtten åt — kontrollparen finns bara"
            "\nför att visa att svaren inte är slumpmässiga."
        )
    return 0


# -- argparse -------------------------------------------------------------------


DEFAULT_INDEX = Path(".fatta/graph.json")


def cmd_index(args: argparse.Namespace) -> int:
    """Bygger indexet för ett TypeScript-projekt på konventionsplatsen."""
    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        tsgraph.emit(args.tsconfig, out)
    except (RuntimeError, FileNotFoundError) as err:
        print(f"fel: {err}", file=sys.stderr)
        return 1
    graph = tsgraph.load(out)
    local = sum(1 for i in graph.items.values() if i.external is None)
    print(f"{out}: {len(graph.items)} items, varav {local} lokala")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    """Samma svar som MCP-verktyget, fast på kommandoraden.

    Finns för att indexet ska gå att använda utan MCP-transport — bland annat i
    A/B-mätningar, där transporten annars blir en variabel som inte hör dit."""
    doc = args.doc or DEFAULT_INDEX
    if not doc.is_file():
        print(f"hittade inget index på {doc}", file=sys.stderr)
        return 1
    _, graph = load_crate(doc, include_docs=True)
    answer = server.what_must_i_know(graph, args.symbol)
    print(answer.as_json())
    return 0 if "error" not in answer.payload else 1


DEFAULT_TESTMAP = Path(".fatta/testmap.json")


def cmd_testmap(args: argparse.Namespace) -> int:
    """Bygger testkartan för ett TypeScript-projekt."""
    try:
        testmap_mod.emit(args.tsconfig, args.out)
    except (RuntimeError, FileNotFoundError) as err:
        print(f"fel: {err}", file=sys.stderr)
        return 1
    tm = testmap_mod.load(args.out)
    exercised = len({t2["name"] for t in tm.tests for t2 in t.targets})
    print(f"{args.out}: {len(tm.tests)} tester, {exercised} symboler spikade")
    return 0


def cmd_tests(args: argparse.Namespace) -> int:
    """Vilka tester spikar en symbol, och vad hävdar de?"""
    path = args.map or DEFAULT_TESTMAP
    if not path.is_file():
        print(f"hittade ingen testkarta på {path}. Bygg: fatta testmap <tsconfig>", file=sys.stderr)
        return 1
    tm = testmap_mod.load(path)
    found = tm.pinning(args.symbol, args.file)
    print(testmap_mod.render(args.symbol, found, tm.mocks))
    return 0 if found else 1


def cmd_serve(args: argparse.Namespace) -> int:
    doc = args.doc or DEFAULT_INDEX
    if not doc.is_file():
        print(
            f"hittade inget index på {doc}. Bygg det med: fatta index <tsconfig.json>",
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
        description="Mäter förståelsefotavtryck (CF) för Rust-kod ur rustdoc-JSON.",
        epilog=(
            "Generera indata med: cargo rustdoc --lib -- -Zunstable-options "
            "--output-format json --document-private-items (kräver nightly)"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="mät och rangordna ett crate")
    scan.add_argument("doc", type=Path, help="sökväg till <crate>.json från rustdoc")
    scan.add_argument("--src-root", type=Path, help="rot för relativa span-sökvägar")
    scan.add_argument("--csv", type=Path, help="skriv resultatet som CSV")
    scan.add_argument("--top", type=int, default=0, help="visa bara de N största")
    scan.add_argument(
        "--no-docs", action="store_true", help="räkna inte doc som del av kontraktet"
    )
    scan.add_argument(
        "--whole-types",
        action="store_true",
        help="ladda för hela typdefinitioner i stället för de medlemmar som används",
    )
    scan.add_argument(
        "--surprisal",
        metavar="MODELL",
        help=(
            "vikta kontrakt efter hur oväntade de är, via en lokal Ollama-modell"
            " (t.ex. qwen2.5-coder:14b)"
        ),
    )
    scan.add_argument(
        "--surprisal-cache",
        type=Path,
        default=Path(".fatta-surprisal.json"),
        help="var vikterna sparas mellan körningar",
    )
    scan.set_defaults(func=cmd_scan)

    pair = sub.add_parser("pairs", help="bygg en blind granskningspack")
    pair.add_argument("docs", type=Path, nargs="+", help="en eller flera <crate>.json")
    pair.add_argument(
        "--out", type=Path, default=Path("granskning"), help="katalog att skriva till"
    )
    pair.add_argument("--n", type=int, default=12, help="antal par totalt")
    pair.add_argument(
        "--controls", type=int, default=3, help="hur många av dem som är kontrollpar"
    )
    pair.add_argument(
        "--no-docs", action="store_true", help="räkna inte doc som del av kontraktet"
    )
    pair.add_argument(
        "--whole-types",
        action="store_true",
        help="ladda för hela typdefinitioner i stället för de medlemmar som används",
    )
    pair.set_defaults(func=cmd_pairs)

    score = sub.add_parser("score", help="jämför ifyllda svar mot facit")
    score.add_argument("facit", type=Path, help="facit.json från pairs")
    score.add_argument(
        "answers", help="ifyllt granskningsark, eller en sträng som ABBA"
    )
    score.set_defaults(func=cmd_score)

    index = sub.add_parser("index", help="bygg indexet för ett TypeScript-projekt")
    index.add_argument("tsconfig", type=Path, help="sökväg till tsconfig.json")
    index.add_argument("--out", type=Path, default=DEFAULT_INDEX)
    index.set_defaults(func=cmd_index)

    ask = sub.add_parser("ask", help="fråga indexet vad man måste veta om en symbol")
    ask.add_argument("symbol", help="funktionens namn")
    ask.add_argument("doc", type=Path, nargs="?", help=f"index (standard: {DEFAULT_INDEX})")
    ask.set_defaults(func=cmd_ask)

    tmap = sub.add_parser("testmap", help="bygg testkartan för ett TypeScript-projekt")
    tmap.add_argument("tsconfig", type=Path)
    tmap.add_argument("--out", type=Path, default=DEFAULT_TESTMAP)
    tmap.set_defaults(func=cmd_testmap)

    tq = sub.add_parser("tests", help="vilka tester spikar en symbol, och vad hävdar de")
    tq.add_argument("symbol")
    tq.add_argument("--map", type=Path, help=f"testkarta (standard: {DEFAULT_TESTMAP})")
    tq.add_argument("--file", help="filtrera på symbolens filväg (vid namnkrockar)")
    tq.set_defaults(func=cmd_tests)

    serve = sub.add_parser("serve", help="kör MCP-servern över ett index")
    serve.add_argument(
        "doc",
        type=Path,
        nargs="?",
        help=f"index att servera (standard: {DEFAULT_INDEX} i arbetskatalogen)",
    )
    serve.add_argument("--src-root", type=Path, help="rot för relativa span-sökvägar")
    serve.add_argument("--testmap", type=Path, help=f"testkarta (standard: {DEFAULT_TESTMAP})")
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
