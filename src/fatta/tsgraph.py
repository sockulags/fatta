"""TypeScript frontend: reads the graph that scripts/ts-graph.mjs writes.

The emitter runs tsc's own type checker, so references are resolved the same way rustdoc
does it for Rust. The core in `graph.py` sees no difference.
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
    """Runs the emitter and returns the path to the graph."""
    if not EMITTER.is_file():
        raise FileNotFoundError(f"emitter not found: {EMITTER}")
    result = subprocess.run(
        ["node", str(EMITTER), str(tsconfig), str(out)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ts-graph failed ({result.returncode}): {result.stderr.strip()}"
        )
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    return out


def parse(data: dict, **graph_args) -> Graph:
    if data.get("format") != FORMAT:
        raise ValueError(f"unknown graph format: {data.get('format')!r}")
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
            calls=tuple(raw.get("calls") or ()),
            owner=tuple(raw.get("owner") or ()),
            external=raw.get("external"),
            file=raw.get("file") or "",
            line=raw.get("line") or 0,
        )
    return Graph(name=data.get("name") or "?", items=items, **graph_args)


def load(path: Path, **graph_args) -> Graph:
    return parse(json.loads(path.read_text(encoding="utf-8")), **graph_args)
