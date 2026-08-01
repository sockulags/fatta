"""Testkartan: funktion → testerna som spikar dess beteende.

A/B/C-mätningen visade att det som avgör om en agent lyckas ändra en funktion inte är
kodförståelse utan om beteendespecifikationen går att hitta — och den bor i testerna,
ofta som enda plats. Kartan gör den slagbar: för en symbol, vilka tester rör den, och
vad hävdar de ordagrant.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

EMITTER = Path(__file__).resolve().parent.parent.parent / "scripts" / "test-map.mjs"
FORMAT = "fatta-testmap/1"


@dataclass(frozen=True)
class TestCase:
    file: str
    suite: str
    name: str
    line: int
    targets: tuple[dict, ...]
    file_targets: tuple[str, ...]
    source_reads: tuple[str, ...] = ()
    casts: tuple[dict, ...] = ()
    expect_errors: int = 0
    assertions: tuple[dict, ...] = ()


@dataclass
class TestMap:
    project: str
    tests: list[TestCase]
    mocks: dict[str, list[str]]
    _by_name: dict[str, list[TestCase]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for test in self.tests:
            for target in test.targets:
                self._by_name.setdefault(target["name"], []).append(test)

    def pinning(self, symbol: str, file_filter: str | None = None) -> list[TestCase]:
        """Testerna som rör `symbol`, hårdast först (flest assertions)."""
        found = self._by_name.get(symbol, [])
        if file_filter:
            found = [
                t for t in found
                if any(
                    target["name"] == symbol and file_filter in target["file"]
                    for target in t.targets
                )
            ]
        return sorted(found, key=lambda t: -len(t.assertions))

    def judge_files(
        self,
        symbol: str,
        file_filter: str | None = None,
        target_file: str | None = None,
    ) -> list[str]:
        """Testfilerna, rankade på hur många av deras tester som rör symbolen.

        Symbolträffar väger tyngre än filträffar: ett test som anropar funktionen är
        starkare belägg än ett som bara läser dess källfil."""
        counts: dict[str, int] = {}
        for test in self.pinning(symbol, file_filter):
            counts[test.file] = counts.get(test.file, 0) + 10
        if target_file:
            wanted = target_file.replace("\\", "/")
            for test in self.tests:
                if any(ft == wanted for ft in test.file_targets):
                    counts[test.file] = counts.get(test.file, 0) + 1
        return [f for f, _ in sorted(counts.items(), key=lambda kv: -kv[1])]

    def untested(self, names: list[str]) -> list[str]:
        return [n for n in names if n not in self._by_name]

    def judge_files_via_graph(
        self, symbol: str, target_file: str, graph, max_depth: int = 3
    ) -> list[str]:
        """Domarkandidater genom produktionskedjan.

        Ett test som spikar en anropare spikar transitivt det anropade: testet för
        komponenten fäller hooken den använder. Grafens anropskanter vänds och följs
        uppåt från symbolen; tester som rör någon av anroparna räknas, närmast först.
        """
        wanted_file = target_file.replace("\\", "/")
        root = next(
            (
                i for i, item in graph.items.items()
                if item.name == symbol and item.file.replace("\\", "/") == wanted_file
            ),
            None,
        )
        if root is None:
            return []

        callers: dict[str, set[str]] = {}
        for item_id, item in graph.items.items():
            for callee in (*item.calls, *item.refs):
                callers.setdefault(callee, set()).add(item_id)

        scores: dict[str, float] = {}
        frontier, seen = {root}, {root}
        for depth in range(1, max_depth + 1):
            frontier = {
                caller
                for node in frontier
                for caller in callers.get(node, ())
                if caller not in seen
            }
            seen |= frontier
            for caller_id in frontier:
                caller = graph.items[caller_id]
                for test in self._by_name.get(caller.name, []):
                    if any(
                        target["name"] == caller.name
                        and target["file"].replace("\\", "/")
                        == caller.file.replace("\\", "/")
                        for target in test.targets
                    ):
                        scores[test.file] = scores.get(test.file, 0) + 1 / depth
        return [f for f, _ in sorted(scores.items(), key=lambda kv: -kv[1])]


def parse(data: dict) -> TestMap:
    if data.get("format") != FORMAT:
        raise ValueError(f"okänt testkarteformat: {data.get('format')!r}")
    tests = [
        TestCase(
            file=raw["file"],
            suite=raw.get("suite") or "",
            name=raw.get("name") or "",
            line=raw.get("line") or 0,
            targets=tuple(raw.get("targets") or ()),
            file_targets=tuple(raw.get("file_targets") or ()),
            source_reads=tuple(raw.get("source_reads") or ()),
            casts=tuple(raw.get("casts") or ()),
            expect_errors=raw.get("expect_errors") or 0,
            assertions=tuple(raw.get("assertions") or ()),
        )
        for raw in data.get("tests") or []
    ]
    return TestMap(
        project=data.get("project") or "?",
        tests=tests,
        mocks=data.get("mocks") or {},
    )


def load(path: Path) -> TestMap:
    return parse(json.loads(path.read_text(encoding="utf-8")))


def emit(tsconfig: Path, out: Path) -> Path:
    if not EMITTER.is_file():
        raise FileNotFoundError(f"hittade inte emittern: {EMITTER}")
    result = subprocess.run(
        ["node", str(EMITTER), str(tsconfig), str(out)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"test-map misslyckades ({result.returncode}): {result.stderr.strip()}"
        )
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    return out


def render(symbol: str, tests: list[TestCase], mocks: dict[str, list[str]]) -> str:
    """Läsbart svar: testerna, deras assertions, och vad som är mockat."""
    if not tests:
        return (
            f"Inga tester rör {symbol!r}. Beteendet är ospecificerat — att ändra det "
            "bryter inget test, vilket är dess egen varning."
        )
    lines = [f"{len(tests)} tester spikar {symbol}:", ""]
    for test in tests:
        title = f"{test.suite} › {test.name}" if test.suite else test.name
        lines.append(f"## {title}")
        lines.append(f"   {test.file}:{test.line}")
        mocked = mocks.get(test.file)
        if mocked:
            lines.append(f"   mockat i filen: {', '.join(sorted(set(mocked))[:6])}")
        for assertion in test.assertions[:12]:
            lines.append(f"   L{assertion['line']}: {assertion['text']}")
        if len(test.assertions) > 12:
            lines.append(f"   … {len(test.assertions) - 12} assertions till")
        lines.append("")
    return "\n".join(lines)
