"""Kommandoradsgränssnitt för fatta."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .metric import Crate, Footprint


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fatta",
        description="Mäter förståelsefotavtryck (CF) för Rust-kod ur rustdoc-JSON.",
        epilog=(
            "Generera indata med: cargo +nightly rustdoc --lib -- "
            "-Zunstable-options --output-format json --document-private-items"
        ),
    )
    parser.add_argument("doc", type=Path, help="sökväg till <crate>.json från rustdoc")
    parser.add_argument(
        "--src-root",
        type=Path,
        help="rot att lösa relativa span-sökvägar mot (standard: crate-roten gissad ur doc)",
    )
    parser.add_argument(
        "--no-docs",
        action="store_true",
        help="räkna inte doc-kommentarer som del av kontraktet",
    )
    parser.add_argument("--csv", type=Path, help="skriv resultatet som CSV till fil")
    parser.add_argument(
        "--top", type=int, default=0, help="visa bara de N största (0 = alla)"
    )
    return parser.parse_args(argv)


def guess_src_root(doc: Path) -> Path:
    """target/doc/<crate>.json ligger tre nivåer under crate-roten."""
    return doc.parent.parent.parent


def load(args: argparse.Namespace) -> Crate:
    doc = json.loads(args.doc.read_text(encoding="utf-8"))
    version = doc.get("format_version")
    if version is not None and version < 55:
        print(
            f"varning: rustdoc-format {version} är äldre än det verktyget testats mot",
            file=sys.stderr,
        )
    return Crate.from_doc(
        doc,
        src_root=args.src_root or guess_src_root(args.doc),
        include_docs=not args.no_docs,
    )


def print_table(rows: list[Footprint], limit: int) -> None:
    shown = rows[:limit] if limit else rows
    header = f"{'funktion':<26}{'LOC':>5}{'kropp':>7}{'slutning':>10}{'CF':>7}   tyngsta beroenden"
    print(header)
    print("-" * len(header))
    for row in shown:
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    crate = load(args)
    rows = sorted(
        (crate.footprint(item_id) for item_id in crate.local_functions()),
        key=lambda row: -row.cf,
    )
    if not rows:
        print("inga lokala funktioner hittades i indata", file=sys.stderr)
        return 1
    print_table(rows, args.top)
    if args.csv:
        write_csv(rows, args.csv)
        print(f"\nskrev {len(rows)} rader till {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
