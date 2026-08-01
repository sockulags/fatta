"""Harness for the A/B experiment: empties a function body and runs the test suite.

A case is valid only if the suite *breaks* when the body is emptied. Otherwise the
function is not covered by any test, and the outcome would be meaningless regardless of
what the agent did.

Run from the root of the codebase under measurement, with a prebuilt graph.
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
    """Everything up to the body's first brace at depth zero."""
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
    raise ValueError("found no body to blank")


@dataclass
class Case:
    name: str
    item_id: str
    file: str
    line: int
    cf: int
    loc: int
    judges: list[str] | None = None
    """The test files a blank body turns red — the case's answer key."""


# The index lives outside the repo on purpose: it stores function bodies, and an agent
# that finds the file can read the original implementation it is supposed to recreate.
GRAPH = Path("../ab-index/graph.json")


def load(graph_path: Path = GRAPH) -> Graph:
    return tsgraph.load(graph_path)


def blank(graph: Graph, item_id: str) -> str:
    """Replaces the body with a stub. Returns the original text."""
    item = graph.get(item_id)
    if item is None or not item.body:
        raise ValueError(f"no item with a body: {item_id}")
    path = Path(item.file)
    # newline="" preserves CRLF. The emitter reads the file raw via Node, so the body in
    # the graph has the file's line endings — reading with universal newlines matches
    # nothing.
    with path.open("r", encoding="utf-8", newline="") as handle:
        text = handle.read()
    body = item.body if item.body in text else item.body.replace("\n", "\r\n")
    if body not in text:
        raise ValueError(f"body not found in {item.file} — is the index current?")
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
    """Red and green test counts from the vitest summary."""
    m = _COUNTS.search(output)
    if not m:
        return {"failed": None, "passed": None}
    return {"failed": int(m.group(1) or 0), "passed": int(m.group(2))}


def failing_test_files(output: str) -> set[str]:
    """Which test files went red. They are the case's judges."""
    return {m.group(1).replace("\\", "/") for m in FAIL_LINE.finditer(output)}


def hide(files: set[str]) -> dict[str, Path]:
    """Moves the judges out of the repo during the agent run.

    Letting the agent read tests is realistic — that is how you implement against a
    spec. Letting it read the very file that decides the case would give away the answer
    key. Hence only the judge is hidden, not tests in general."""
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
    # shell=True requires a string on Windows; with a list only the first element is
    # used and the output becomes None.
    result = subprocess.run(
        "pnpm exec vitest run --reporter=dot",
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=True,
        # The Windows locale is cp1252; vitest writes UTF-8. Decoding fails without this.
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode == 0, (result.stdout or "") + (result.stderr or "")


def validate(graph: Graph, cases: list[Case]) -> list[Case]:
    """Keeps only cases where a blank body makes the suite fail."""
    keepers = []
    for case in cases:
        try:
            blank(graph, case.item_id)
        except ValueError as err:
            print(f"  {case.name:<30} SKIPPED — {err}")
            restore()
            continue
        passed, output = run_tests()
        restore()
        if passed:
            print(f"  {case.name:<30} uncovered (suite green with blank body)")
            continue
        case.judges = sorted(failing_test_files(output))
        print(f"  {case.name:<30} valid  CF={case.cf}  judges: {len(case.judges)}")
        keepers.append(case)
    return keepers


def cases_from(path: Path) -> list[Case]:
    return [Case(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


if __name__ == "__main__":
    graph = load()
    cases = cases_from(Path(sys.argv[1]))
    print(f"validating {len(cases)} candidates\n")
    keepers = validate(graph, cases)
    out = Path("ab-valid.json")
    out.write_text(
        json.dumps([c.__dict__ for c in keepers], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n{len(keepers)} valid cases written to {out}")
