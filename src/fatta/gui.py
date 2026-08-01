"""Local GUI over the same dispatch as the MCP server.

The GUI is a thin HTTP surface: `POST /api {name, arguments}` goes straight into
`server.dispatch`, i.e. exactly the operations an agent reaches via MCP. One capability,
two transports — add a tool to the dispatch and it exists in both.
"""

from __future__ import annotations

import json
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import server as mcp
from .graph import Graph

PAGE = Path(__file__).resolve().parent / "gui.html"


class Handler(BaseHTTPRequestHandler):
    graph: Graph
    tmap = None
    repo = "."

    def log_message(self, *args) -> None:  # quiet — the terminal is not a log file
        pass

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, b"finns inte", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/api":
            self._send(404, b"finns inte", "text/plain")
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
            arguments = request.get("arguments") or {}
            if request.get("name") == "test_health":
                arguments.setdefault("repo", self.repo)
            answer = mcp.dispatch(self.graph, request.get("name", ""), arguments, self.tmap)
            body = json.dumps(answer.payload, ensure_ascii=False).encode()
            self._send(200, body, "application/json; charset=utf-8")
        except Exception as err:  # the GUI should show the error, not die
            body = json.dumps({"error": str(err)}, ensure_ascii=False).encode()
            self._send(500, body, "application/json; charset=utf-8")


def serve_gui(
    graph: Graph, tmap=None, port: int = 4715, repo: str = ".", open_browser: bool = True
) -> None:
    handler = partial(Handler)
    Handler.graph = graph
    Handler.tmap = tmap
    Handler.repo = repo
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}"
    print(f"fatta gui: {url}  (stop with Ctrl+C)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
