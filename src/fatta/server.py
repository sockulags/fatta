"""MCP-server över förståelseindexet.

Skillnaden mot vanlig kodsökning är att svaren är **avgränsade**. En sökning ger relevant
text utan botten — du vet aldrig när du sett tillräckligt. Det här ger en sluten mängd:
det här är allt, du kan sluta läsa.

Varje uppgift bär sin härkomst. I den här versionen är allt `derived`, alltså härlett ur
koden och sant per konstruktion. Påstådda fakta som ingen kontrollerar finns med flit inte
med — en uppgift som får en agent att sluta läsa måste vara sann, annars är den värre än
ingen uppgift alls.
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
    """Ett avgränsat svar: mängden, kostnaden, och vad som inte kunde tas med."""

    symbol: str
    payload: dict[str, Any]

    def as_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, indent=2)


def resolve(graph: Graph, symbol: str) -> list[str]:
    """Alla lokala funktioner som heter `symbol`. Namn är inte unika."""
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
            # Externt paket vi inte har någon graf för. Att tiga om det vore att
            # utge mängden för sluten när den inte är det.
            unavailable.append(
                {
                    "name": graph.name_of(dep),
                    "from": entry.external if entry else "?",
                    "why": "ingen graf för det paketet",
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
            "Mängden är sluten: har du läst allt under must_know behöver du inte gå "
            "djupare."
            if not unavailable
            else "Mängden är inte sluten — se unavailable."
        ),
    }


def what_must_i_know(graph: Graph, symbol: str) -> Answer:
    matches = resolve(graph, symbol)
    if not matches:
        return Answer(symbol, {"error": f"hittade ingen funktion {symbol!r}"})
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
    """Var ett pålitligt kontrakt skulle spara mest.

    En doc djupt ner i trädet sparar nästan ingenting — man var tvungen att gå dit för
    att läsa den. Värdet av en doc är storleken på det subträd den beskär."""
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
    """Testerna som spikar en symbols beteende — direkt eller genom anropskedjan.

    Det här är svaret på det A/B/C-mätningen visade: specifikationen bor i testerna.
    Läses de innan man ändrar är man inte längre hänvisad till att gissa literaler."""
    if tmap is None:
        return Answer(symbol, {"error": "ingen testkarta laddad — bygg med: fatta testmap"})
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
                "Tom lista betyder att beteendet är ospecificerat — att ändra det "
                "bryter inget test, vilket är dess egen varning."
                if not direct and not via
                else "Läs read_these_first innan du ändrar symbolen."
            ),
        },
    )


TOOLS = [
    {
        "name": "which_tests_pin",
        "description": (
            "Testerna som spikar en symbols beteende, med deras assertions ordagrant. "
            "Läs dem FÖRST vid ändringar — beteendekrav bor ofta enbart där."
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
            "Den minsta slutna mängd du måste förstå för att kunna ändra en funktion, "
            "med kontrakt och härkomst. Har du läst allt i must_know behöver du inte "
            "gräva djupare."
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
            "Var i kodbasen ett pålitligt kontrakt skulle bespara mest läsning, rankat."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
]


def dispatch(graph: Graph, name: str, arguments: dict, tmap=None) -> Answer:
    if name == "which_tests_pin":
        return which_tests_pin(graph, tmap, arguments.get("symbol", ""), arguments.get("file_hint"))
    if name == "what_must_i_know":
        return what_must_i_know(graph, arguments.get("symbol", ""))
    if name == "doc_leverage":
        return doc_leverage(graph, int(arguments.get("limit", 20)))
    return Answer(name, {"error": f"okänt verktyg {name!r}"})


def handle(graph: Graph, message: dict, tmap=None) -> dict | None:
    """Ett JSON-RPC-svar, eller None för notifieringar som inte ska besvaras."""
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
        return None  # notifiering, till exempel notifications/initialized
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"okänd metod {method!r}"},
        }

    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve(graph: Graph, stdin=None, stdout=None, tmap=None) -> None:
    """Läser JSON-RPC rad för rad från stdin och svarar på stdout."""
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
