"""Tester för MCP-servern. Transporten testas via handle(), inte via en riktig process."""

from __future__ import annotations

import io
import json

import pytest

from fatta import server
from fatta.graph import FUNCTION, MEMBER, TYPE, Graph, Item


def tiny_graph() -> Graph:
    """En liten kodbas: en funktion som rör en typ, som i sin tur rör en okänd extern."""
    items = {
        "f": Item(
            id="f",
            name="handle",
            kind=FUNCTION,
            contract="fn handle(cfg: &Config) -> u32",
            body="fn handle(cfg: &Config) -> u32 { cfg.limit }",
            refs=("T",),
            file="src/lib.rs",
            line=3,
        ),
        "T": Item(
            id="T",
            name="Config",
            kind=TYPE,
            contract="struct Config",
            members=("m",),
            file="src/lib.rs",
            line=10,
        ),
        "m": Item(id="m", name="limit", kind=MEMBER, contract="limit: u32"),
        "known": Item(id="known", name="String", kind=TYPE, contract="", external="std"),
    }
    return Graph(name="tiny", items=items)


def call(graph: Graph, tool: str, arguments: dict) -> dict:
    response = server.handle(
        graph,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
    )
    return json.loads(response["result"]["content"][0]["text"])


def test_svaret_ar_avgransat_nar_allt_finns() -> None:
    payload = call(tiny_graph(), "what_must_i_know", {"symbol": "handle"})

    assert payload["bounded"] is True
    assert [entry["name"] for entry in payload["must_know"]] == ["Config"]
    assert payload["unavailable"] == []


def test_allt_bar_harkomst() -> None:
    payload = call(tiny_graph(), "what_must_i_know", {"symbol": "handle"})

    assert {entry["provenance"] for entry in payload["must_know"]} == {"derived"}


def test_okand_extern_gor_mangden_oavgransad() -> None:
    """Att tiga om ett paket vi saknar graf för vore att utge mängden för sluten när den
    inte är det — och då slutar agenten läsa på fel ställe."""
    graph = tiny_graph()
    graph.items["T"] = Item(
        id="T", name="Config", kind=TYPE, contract="struct Config", refs=("X",)
    )
    graph.items["X"] = Item(
        id="X", name="Foreign", kind=TYPE, contract="", external="some-crate"
    )

    payload = call(graph, "what_must_i_know", {"symbol": "handle"})

    assert payload["bounded"] is False
    assert payload["unavailable"][0]["from"] == "some-crate"


def test_kostnaden_delas_upp() -> None:
    payload = call(tiny_graph(), "what_must_i_know", {"symbol": "handle"})
    cost = payload["cost"]

    assert cost["cf"] == cost["own_body"] + cost["closure"]
    assert cost["own_body"] > 0


def test_okand_symbol_ger_fel_inte_tomt_svar() -> None:
    payload = call(tiny_graph(), "what_must_i_know", {"symbol": "saknas"})

    assert "error" in payload


def test_doc_leverage_rankar_pa_besparing() -> None:
    payload = call(tiny_graph(), "doc_leverage", {"limit": 5})

    assert payload["ranked"], "inget rankat"
    values = [row["would_prune"] for row in payload["ranked"]]
    assert values == sorted(values, reverse=True)


def test_tools_list_beskriver_bada_verktygen() -> None:
    response = server.handle(tiny_graph(), {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    assert {t["name"] for t in response["result"]["tools"]} == {
        "what_must_i_know",
        "doc_leverage",
    }


def test_initialize_svarar_med_protokollversion() -> None:
    response = server.handle(tiny_graph(), {"jsonrpc": "2.0", "id": 0, "method": "initialize"})

    assert response["result"]["protocolVersion"] == server.PROTOCOL_VERSION
    assert response["result"]["serverInfo"]["name"] == "fatta"


def test_notifiering_besvaras_inte() -> None:
    """En notifiering saknar id. Svarar man på den bryter man JSON-RPC."""
    assert server.handle(tiny_graph(), {"method": "notifications/initialized"}) is None


def test_okand_metod_ger_jsonrpc_fel() -> None:
    response = server.handle(tiny_graph(), {"jsonrpc": "2.0", "id": 9, "method": "nope"})

    assert response["error"]["code"] == -32601


def test_serve_lasser_rader_och_svarar() -> None:
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    out = io.StringIO()

    server.serve(tiny_graph(), stdin=io.StringIO(request + "\n"), stdout=out)

    assert json.loads(out.getvalue())["id"] == 1


def test_trasig_rad_kraschar_inte_servern() -> None:
    out = io.StringIO()
    stdin = io.StringIO('inte json\n{"jsonrpc":"2.0","id":4,"method":"tools/list"}\n')

    server.serve(tiny_graph(), stdin=stdin, stdout=out)

    assert json.loads(out.getvalue())["id"] == 4
