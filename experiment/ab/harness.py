"""Harness för A/B-mätningen: tömmer en funktionskropp och kör testsviten.

Ett fall är giltigt bara om sviten *går sönder* när kroppen töms. Annars täcks inte
funktionen av något test, och utfallet hade varit meningslöst oavsett vad agenten gjorde.

Körs från roten av kodbasen som mäts, med ett färdigbyggt .fatta/graph.json.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from fatta import tsgraph
from fatta.graph import Graph

STUB = 'throw new Error("fatta-ab: not implemented");'


def signature_of(body: str) -> str:
    """Allt fram till kroppens första klammer på djup noll."""
    depth = 0
    previous = ""
    for index, char in enumerate(body):
        if char in "(<[":
            depth += 1
        elif char in ")]" or (char == ">" and previous not in "-=" ):
            depth = max(0, depth - 1)
        elif char == "{" and depth == 0:
            return body[:index].rstrip()
        previous = char
    raise ValueError("hittade ingen kropp att tömma")


@dataclass
class Case:
    name: str
    item_id: str
    file: str
    line: int
    cf: int
    loc: int
    judges: list[str] | None = None
    """Testfilerna som blir röda av en tom kropp — fallets facit."""


# Indexet ligger utanför repot med flit: det lagrar funktionskroppar, och en agent som
# hittar filen kan läsa originalimplementationen den ska återskapa.
GRAPH = Path("../ab-index/graph.json")


def load(graph_path: Path = GRAPH) -> Graph:
    return tsgraph.load(graph_path)


def blank(graph: Graph, item_id: str) -> str:
    """Ersätter kroppen med en stub. Returnerar originaltexten."""
    item = graph.get(item_id)
    if item is None or not item.body:
        raise ValueError(f"inget item med kropp: {item_id}")
    path = Path(item.file)
    # newline="" bevarar CRLF. Emittern läser filen rå via Node, så kroppen i grafen har
    # filens radslut — läser Python med universella radslut matchar ingenting.
    with path.open("r", encoding="utf-8", newline="") as handle:
        text = handle.read()
    body = item.body if item.body in text else item.body.replace("\n", "\r\n")
    if body not in text:
        raise ValueError(f"hittade inte kroppen i {item.file} — är indexet aktuellt?")
    stub = f"{signature_of(body)} {{\n  {STUB}\n}}"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text.replace(body, stub, 1))
    return body


def restore() -> None:
    subprocess.run(["git", "checkout", "--", "."], check=True, capture_output=True)


FAIL_LINE = re.compile(r"FAIL\s+(\S+\.(?:test|spec)\.[tj]sx?)")
HIDDEN_ROOT = Path("../.fatta-ab-hidden")


_COUNTS = re.compile(r"Tests\s+(?:(\d+) failed \| )?(\d+) passed")


def test_counts(output: str) -> dict:
    """Antal röda och gröna tester ur vitest-sammanfattningen."""
    m = _COUNTS.search(output)
    if not m:
        return {"failed": None, "passed": None}
    return {"failed": int(m.group(1) or 0), "passed": int(m.group(2))}


def failing_test_files(output: str) -> set[str]:
    """Vilka testfiler som blev röda. De är fallets domare."""
    return {m.group(1).replace("\\", "/") for m in FAIL_LINE.finditer(output)}


def hide(files: set[str]) -> dict[str, Path]:
    """Flyttar domarna ut ur repot under agentkörningen.

    Att låta agenten läsa tester är realistiskt — det är så man implementerar mot spec.
    Att låta den läsa just den fil som avgör fallet vore att ge bort facit. Därför göms
    bara domaren, inte tester i allmänhet."""
    moved: dict[str, Path] = {}
    for name in files:
        source = Path(name)
        if not source.is_file():
            continue
        target = HIDDEN_ROOT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
        moved[name] = target
    return moved


def unhide(moved: dict[str, Path]) -> None:
    for name, target in moved.items():
        destination = Path(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        target.replace(destination)


def run_tests(timeout: int = 600) -> tuple[bool, str]:
    # shell=True kräver en sträng på Windows; med en lista tas bara första elementet
    # och utdata blir None.
    result = subprocess.run(
        "pnpm exec vitest run --reporter=dot",
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=True,
        # Windows-locale är cp1252; vitest skriver UTF-8. Utan detta faller avkodningen.
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode == 0, (result.stdout or "") + (result.stderr or "")


def validate(graph: Graph, cases: list[Case]) -> list[Case]:
    """Behåller bara fall där tömd kropp får sviten att fallera."""
    keepers = []
    for case in cases:
        try:
            blank(graph, case.item_id)
        except ValueError as err:
            print(f"  {case.name:<30} HOPPAS ÖVER — {err}")
            restore()
            continue
        passed, output = run_tests()
        restore()
        if passed:
            print(f"  {case.name:<30} otäckt (sviten grön med tom kropp)")
            continue
        case.judges = sorted(failing_test_files(output))
        print(f"  {case.name:<30} giltig  CF={case.cf}  domare: {len(case.judges)}")
        keepers.append(case)
    return keepers


def cases_from(path: Path) -> list[Case]:
    return [Case(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


if __name__ == "__main__":
    graph = load()
    cases = cases_from(Path(sys.argv[1]))
    print(f"validerar {len(cases)} kandidater\n")
    keepers = validate(graph, cases)
    out = Path("ab-valid.json")
    out.write_text(
        json.dumps([c.__dict__ for c in keepers], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n{len(keepers)} giltiga fall skrivna till {out}")
