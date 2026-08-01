"""Kör ett fall i taget genom harnesset och skriver ner utfallet.

    python runner.py setup <fall-index>
    python runner.py finish <fall-index> <arm> <tokens> <filer>

setup tömmer kroppen och gömmer domarna. finish återställer domarna, kör sviten,
antecknar resultatet i ab-results.json och städar repot.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import harness

# All experimentdata ligger utanför repot. Låg den kvar i arbetsträdet kunde agenten
# läsa vilken testfil som gömts — inte facit, men en vink som förstör mätningen.
META = Path("../ab-meta")
CASES = META / "ab-ordered.json"
HIDDEN = META / "ab-hidden.json"
RESULTS = META / "ab-results.json"


def case(index: int) -> dict:
    return json.loads(CASES.read_text(encoding="utf-8"))[index]


def setup(index: int) -> None:
    harness.restore()
    current = case(index)
    graph = harness.load()
    harness.blank(graph, current["item_id"])
    moved = harness.hide(set(current["judges"]))
    HIDDEN.write_text(
        json.dumps({k: str(v) for k, v in moved.items()}), encoding="utf-8"
    )
    leaked = [
        str(p)
        for name in current["judges"]
        for p in Path(".").rglob(Path(name).name)
        if "node_modules" not in str(p)
    ]
    if leaked:
        raise SystemExit(f"AVBRYTER: domaren finns kvar någonstans: {leaked}")
    print(f"fall {index + 1}: {current['name']} | CF {current['cf']} | {current['file']}")
    print(f"  gömda domare: {len(moved)}")


def finish(index: int, arm: str, tokens: int, files: int) -> None:
    moved = {k: Path(v) for k, v in json.loads(HIDDEN.read_text(encoding="utf-8")).items()}
    harness.unhide(moved)
    passed, output = harness.run_tests()
    current = case(index)
    row = {
        "case": current["name"],
        "cf": current["cf"],
        "loc": current["loc"],
        "arm": arm,
        "passed": passed,
        "tokens": tokens,
        "files": files,
        "failing": sorted(harness.failing_test_files(output)) if not passed else [],
        # Binärt utfall mättas när domaren spikar literaler som bara finns i domaren;
        # andelen gröna tester är det mått som faktiskt skiljer armarna åt.
        "test_counts": harness.test_counts(output),
    }
    rows = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.is_file() else []
    rows.append(row)
    RESULTS.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    harness.restore()
    print(f"{current['name']} arm {arm}: {'GRÖN' if passed else 'RÖD'}  {tokens} tokens")
    if not passed:
        print(f"  röda: {', '.join(row['failing'])}")


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "setup":
        setup(int(sys.argv[2]))
    elif command == "finish":
        finish(int(sys.argv[2]), sys.argv[3], int(sys.argv[4]), int(sys.argv[5]))
    else:
        raise SystemExit(f"okänt kommando: {command}")
