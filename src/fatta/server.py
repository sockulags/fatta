"""MCP server over the comprehension index.

What separates this from ordinary code search is that the answers are **bounded**. A
search returns relevant text with no bottom — you never know when you have seen enough.
This returns a closed set: this is everything, you can stop reading.

Every fact carries its provenance. In this version everything is `derived`, i.e. extracted
from the code and true by construction. Asserted facts nobody checks are deliberately
absent — a fact that makes an agent stop reading must be true, or it is worse than no
fact at all.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Callable

from .graph import Graph, used_names
from . import testmap as testmap_mod

PROTOCOL_VERSION = "2025-06-18"


@dataclass
class Answer:
    """A bounded answer: the set, the cost, and what could not be included."""

    symbol: str
    payload: dict[str, Any]

    def as_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, indent=2)


def resolve(graph: Graph, symbol: str) -> list[str]:
    """All local functions named `symbol`. Names are not unique."""
    return [i for i in graph.local_functions() if graph.name_of(i) == symbol]


def describe(graph: Graph, item_id: str) -> dict[str, Any]:
    item = graph.get(item_id)
    footprint = graph.footprint(item_id)
    used = used_names(graph.body_text(item_id)) if graph.use_directed else None

    must_know = []
    unavailable = []
    for dep in sorted(graph.closure(item_id, used), key=graph.name_of):
        if graph.is_free(dep):
            continue
        contract = graph.contract_text(dep, used)
        entry = graph.get(dep)
        if not contract.strip():
            # An external package we have no graph for. Staying silent would pass the
            # set off as closed when it is not.
            unavailable.append(
                {
                    "name": graph.name_of(dep),
                    "from": entry.external if entry else "?",
                    "why": "no graph for that package",
                }
            )
            continue
        must_know.append(
            {
                "name": graph.name_of(dep),
                "kind": entry.kind if entry else "?",
                "contract": contract,
                "provenance": "derived",
                "at": f"{entry.file}:{entry.line}" if entry else "",
            }
        )

    return {
        "symbol": graph.name_of(item_id),
        "at": f"{item.file}:{item.line}" if item else "",
        "cost": {
            "cf": footprint.cf,
            "own_body": footprint.body_tokens,
            "closure": footprint.closure_tokens,
            "lines": footprint.loc,
        },
        "must_know": must_know,
        "already_known": footprint.free_count,
        "unavailable": unavailable,
        "bounded": not unavailable,
        "note": (
            "The set is closed: once you have read everything under must_know you need "
            "not go deeper."
            if not unavailable
            else "The set is not closed — see unavailable."
        ),
    }


def what_must_i_know(graph: Graph, symbol: str) -> Answer:
    matches = resolve(graph, symbol)
    if not matches:
        return Answer(symbol, {"error": f"no function named {symbol!r}"})
    if len(matches) == 1:
        return Answer(symbol, describe(graph, matches[0]))
    return Answer(
        symbol,
        {
            "symbol": symbol,
            "ambiguous": True,
            "matches": [describe(graph, item_id) for item_id in matches],
        },
    )


def doc_leverage(graph: Graph, limit: int = 20) -> Answer:
    """Where a trustworthy contract would save the most.

    A doc deep down the tree saves almost nothing — you had to walk there to read it. The
    value of a doc is the size of the subtree it prunes."""
    scored = []
    for item_id, item in graph.items.items():
        if item.external is not None:
            continue
        value = graph.pruning_value(item_id)
        if value:
            scored.append(
                {
                    "name": item.name,
                    "at": f"{item.file}:{item.line}",
                    "would_prune": value,
                }
            )
    scored.sort(key=lambda row: -row["would_prune"])
    return Answer("doc_leverage", {"ranked": scored[:limit]})


def which_tests_pin(graph: Graph, tmap, symbol: str, file_hint: str | None) -> Answer:
    """The tests pinning a symbol's behavior — directly or through the call chain.

    This is the answer to what the A/B/C experiment showed: the specification lives in
    the tests. Read them before changing and you are no longer left guessing literals."""
    if tmap is None:
        return Answer(symbol, {"error": "no test map loaded — build one with: fatta testmap"})
    direct = tmap.pinning(symbol, file_hint)
    files = tmap.judge_files(symbol, file_hint)
    target_file = None
    for item in graph.items.values():
        if item.name == symbol and item.external is None:
            target_file = item.file
            break
    via = (
        tmap.judge_files_via_graph(symbol, target_file, graph) if target_file else []
    )
    return Answer(
        symbol,
        {
            "symbol": symbol,
            "read_these_first": files + [f for f in via if f not in files],
            "tests": [
                {
                    "file": t.file,
                    "name": f"{t.suite} › {t.name}" if t.suite else t.name,
                    "line": t.line,
                    "assertions": [a["text"] for a in t.assertions[:8]],
                    "mocked": sorted(set(tmap.mocks.get(t.file, [])))[:6],
                }
                for t in direct[:10]
            ],
            "note": (
                "An empty list means the behavior is unspecified — changing it breaks "
                "no test, which is its own warning."
                if not direct and not via
                else "Read read_these_first before changing the symbol."
            ),
        },
    )


def list_symbols(graph: Graph) -> Answer:
    """All local functions — the navigation surface for both GUI and agent."""
    rows = sorted(
        (
            {"name": item.name, "file": item.file, "line": item.line}
            for item in (graph.get(i) for i in graph.local_functions())
            if item is not None
        ),
        key=lambda row: (row["file"], row["line"]),
    )
    return Answer("list_symbols", {"symbols": rows, "count": len(rows)})


def test_health(graph: Graph, tmap, repo: str = ".") -> Answer:
    """The cleanup queue as data: the same analysis as `fatta testhealth`, for both surfaces."""
    from pathlib import Path

    from . import testhealth as th

    if tmap is None:
        return Answer("test_health", {"error": "no test map loaded"})
    findings = th.analyze(tmap, graph)
    churn = th.measure_churn(tmap, Path(repo))
    return Answer(
        "test_health",
        {
            "findings": [
                {
                    "file": f.test.file,
                    "line": f.test.line,
                    "name": f"{f.test.suite} › {f.test.name}" if f.test.suite else f.test.name,
                    "score": f.score,
                    "reasons": f.reasons,
                }
                for f in findings
            ],
            "churn": [
                {"file": file, "total": c.total, "test_only": c.test_only}
                for file, c in sorted(churn.items(), key=lambda kv: -kv[1].test_only)
                if c.test_only >= 2
            ],
        },
    )


TOOLS = [
    {
        "name": "list_symbols",
        "description": "All local functions with file and line — the navigation surface.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "test_health",
        "description": (
            "Tests pinning states production cannot produce, ranked, plus test files "
            "fixed without their targets changing."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "which_tests_pin",
        "description": (
            "The tests pinning a symbol's behavior, with their assertions verbatim. "
            "Read them FIRST when changing — behavioral requirements often live only there."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "file_hint": {"type": "string"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "what_must_i_know",
        "description": (
            "The minimal closed set you must understand to change a function, with "
            "contracts and provenance. Once you have read everything in must_know you "
            "need not dig deeper."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "doc_leverage",
        "description": (
            "Where in the codebase a trustworthy contract would save the most reading, ranked."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
]


def dispatch(graph: Graph, name: str, arguments: dict, tmap=None) -> Answer:
    if name == "list_symbols":
        return list_symbols(graph)
    if name == "test_health":
        return test_health(graph, tmap, arguments.get("repo", "."))
    if name == "which_tests_pin":
        return which_tests_pin(graph, tmap, arguments.get("symbol", ""), arguments.get("file_hint"))
    if name == "what_must_i_know":
        return what_must_i_know(graph, arguments.get("symbol", ""))
    if name == "doc_leverage":
        return doc_leverage(graph, int(arguments.get("limit", 20)))
    return Answer(name, {"error": f"unknown tool {name!r}"})


def handle(graph: Graph, message: dict, tmap=None) -> dict | None:
    """A JSON-RPC response, or None for notifications that must not be answered."""
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fatta", "version": "0.1.0"},
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        answer = dispatch(graph, params.get("name", ""), params.get("arguments") or {}, tmap)
        result = {"content": [{"type": "text", "text": answer.as_json()}]}
    elif request_id is None:
        return None  # a notification, e.g. notifications/initialized
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"unknown method {method!r}"},
        }

    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve(graph: Graph, stdin=None, stdout=None, tmap=None) -> None:
    """Reads JSON-RPC line by line from stdin and answers on stdout."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(graph, message, tmap)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
