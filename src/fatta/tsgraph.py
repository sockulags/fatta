"""Frontend för TypeScript: läser grafen som scripts/ts-graph.mjs skriver.

Emittern kör tsc:s egen typcheckare, så referenserna är upplösta på samma sätt som
rustdoc gör det för Rust. Kärnan i `graph.py` ser ingen skillnad.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .graph import Graph, Item

EMITTER = Path(__file__).resolve().parent.parent.parent / "scripts" / "ts-graph.mjs"
FORMAT = "fatta-graph/1"


def emit(tsconfig: Path, out: Path) -> Path:
    """Kör emittern och returnerar sökvägen till grafen."""
    if not EMITTER.is_file():
        raise FileNotFoundError(f"hittade inte emittern: {EMITTER}")
    result = subprocess.run(
        ["node", str(EMITTER), str(tsconfig), str(out)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ts-graph misslyckades ({result.returncode}): {result.stderr.strip()}"
        )
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    return out


def parse(data: dict, **graph_args) -> Graph:
    if data.get("format") != FORMAT:
        raise ValueError(f"okänt grafformat: {data.get('format')!r}")
    items: dict[str, Item] = {}
    for item_id, raw in data["items"].items():
        items[item_id] = Item(
            id=item_id,
            name=raw.get("name") or "",
            kind=raw.get("kind") or "type",
            contract=raw.get("contract") or "",
            body=raw.get("body") or "",
            members=tuple(raw.get("members") or ()),
            refs=tuple(raw.get("refs") or ()),
            owner=tuple(raw.get("owner") or ()),
            external=raw.get("external"),
            file=raw.get("file") or "",
            line=raw.get("line") or 0,
        )
    return Graph(name=data.get("name") or "?", items=items, **graph_args)


def load(path: Path, **graph_args) -> Graph:
    return parse(json.loads(path.read_text(encoding="utf-8")), **graph_args)
