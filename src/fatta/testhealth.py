"""Städkön: tester som spikar tillstånd produktionen inte kan producera.

Äkta onåbarhet är oavgörbar, men fabricerade fall lämnar fingeravtryck — för att bygga
ett tillstånd produktionen aldrig bygger måste testet bryta sig ur något:

- **typsystemet**: `as any`/`as unknown` eller `@ts-expect-error` i testet
- **ingångsvägen**: direktanrop av en intern funktion som produktionen bara når genom
  validerande entrypoints
- **verkligheten**: källäsande tester som regexar produktionsfilen och därmed fäller
  varje refaktorering, även beteendebevarande
- **kontraktsnivån**: långa literaler spikade på interna funktioner — kopietester som
  bryts av varje strängändring

Utfallet är en granskningskö med belägg per rad, inte en dom: varje signal har legitima
undantag (partiella fixturer, medveten isolering, avsiktliga copy-kontrakt vid entrypoints).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .graph import Graph
from .testmap import TestCase, TestMap

# expect(x).toBe('lång literal') — kopietestets form. Korta literaler ('COMPLETED') är
# oftast medvetna kontrakt; längden är vad som skiljer statuskod från kopia.
_LITERAL_PIN = re.compile(r"\.(toBe|toEqual|toContain|toMatch)\(\s*['\"](.{15,}?)['\"]")

WEIGHTS = {"fabricated": 3, "below_waterline": 1, "source_reader": 3, "literal_pin": 2}


@dataclass
class Finding:
    test: TestCase
    reasons: list[str] = field(default_factory=list)
    score: int = 0

    def add(self, kind: str, detail: str) -> None:
        self.reasons.append(f"[{kind}] {detail}")
        self.score += WEIGHTS.get(kind, 1)


def internal_symbols(graph: Graph) -> set[tuple[str, str]]:
    """(fil, namn) för funktioner som har produktionsanropare — alltså inte entrypoints.

    Ett test som anropar en sådan direkt kringgår vägen produktionen tar dit, inklusive
    validering på vägen. Det är inte fel i sig, men det är där omöjliga fall uppstår."""
    called: set[str] = set()
    for item in graph.items.values():
        if item.external is None:
            called.update(item.calls)
    return {
        (graph.items[i].file.replace("\\", "/"), graph.items[i].name)
        for i in called
        if i in graph.items and graph.items[i].external is None
    }


def analyze(tm: TestMap, graph: Graph | None = None) -> list[Finding]:
    internals = internal_symbols(graph) if graph is not None else set()
    findings: list[Finding] = []

    for test in tm.tests:
        finding = Finding(test=test)
        has_prod_targets = bool(test.targets)

        if test.casts and has_prod_targets:
            first = test.casts[0]
            finding.add(
                "fabricated",
                f"{len(test.casts)} typkast, t.ex. L{first['line']}: {first['text']}",
            )
        if test.expect_errors and has_prod_targets:
            finding.add("fabricated", f"{test.expect_errors} st @ts-expect-error/@ts-ignore")

        for read in test.source_reads:
            finding.add("source_reader", f"läser källkoden i {read}")

        direct_internals = [
            t for t in test.targets
            if (t["file"].replace("\\", "/"), t["name"]) in internals
        ]

        pins = [
            (a["line"], m.group(2)[:60])
            for a in test.assertions
            if (m := _LITERAL_PIN.search(a["text"]))
        ]
        if pins and direct_internals:
            line, literal = pins[0]
            finding.add(
                "literal_pin",
                f"{len(pins)} literalspik(ar) på intern funktion, t.ex. L{line}: '{literal}'",
            )

        # Vattenlinjen är kontext, inte anklagelse: att enhetstesta interna funktioner
        # är normalt. Den läggs bara till när en annan signal redan slagit — då säger
        # den *var* det fabricerade tillståndet uppstod: nedanför valideringen.
        if finding.reasons and direct_internals:
            names = ", ".join(sorted({t["name"] for t in direct_internals})[:4])
            finding.add("below_waterline", f"direktanropar interna: {names}")

        if finding.reasons:
            findings.append(finding)

    return sorted(findings, key=lambda f: -f.score)


def render(findings: list[Finding], limit: int = 25) -> str:
    if not findings:
        return "Inga fabrikationssignaler hittade."
    by_kind: dict[str, int] = {}
    for finding in findings:
        for reason in finding.reasons:
            kind = reason.split("]")[0].lstrip("[")
            by_kind[kind] = by_kind.get(kind, 0) + 1
    lines = [
        f"{len(findings)} tester flaggade (av signalstyrka, starkast först).",
        "Kategorier: "
        + ", ".join(f"{k}: {v}" for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "",
    ]
    for finding in findings[:limit]:
        test = finding.test
        title = f"{test.suite} › {test.name}" if test.suite else test.name
        lines.append(f"## [{finding.score}p] {title}")
        lines.append(f"   {test.file}:{test.line}")
        for reason in finding.reasons:
            lines.append(f"   {reason}")
        lines.append("")
    if len(findings) > limit:
        lines.append(f"… {len(findings) - limit} till. Kör med --limit 0 för alla.")
    return "\n".join(lines)


# -- historiken -----------------------------------------------------------------


SEP = chr(1)  # %x01 i git-formatsträngen


@dataclass(frozen=True)
class Churn:
    total: int
    """Commits som rört testfilen."""
    test_only: int
    """Commits som rört testfilen utan att röra någon av dess produktionsmålfiler.

    Det är den rena underhållskostnaden: testet behövde lagas fast beteendet det
    påstås skydda inte ändrades."""


def parse_git_log(text: str) -> list[set[str]]:
    """`git log --name-only --pretty=format:%x01%H` → en filmängd per commit."""
    commits: list[set[str]] = []
    for block in text.split(SEP):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if lines:
            commits.append({l.replace("\\", "/") for l in lines[1:]})
    return commits


def measure_churn(tm: TestMap, repo: Path) -> dict[str, Churn]:
    """Testfil → churn, ur repots faktiska historik.

    `repo` får vara en paketkatalog i ett monorepo: git-loggens sökvägar är alltid
    repo-rotrelativa, så kartans paketrelativa sökvägar prefixas med `--show-prefix`."""
    result = subprocess.run(
        ["git", "log", "--name-only", "--pretty=format:%x01%H"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return {}
    commits = parse_git_log(result.stdout or "")
    prefix_result = subprocess.run(
        ["git", "rev-parse", "--show-prefix"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    prefix = (prefix_result.stdout or "").strip().replace("\\", "/") if prefix_result.returncode == 0 else ""
    if prefix:
        commits = [
            {f[len(prefix):] for f in commit if f.startswith(prefix)}
            for commit in commits
        ]

    targets_by_file: dict[str, set[str]] = {}
    for test in tm.tests:
        bucket = targets_by_file.setdefault(test.file, set())
        bucket.update(t["file"].replace("\\", "/") for t in test.targets)
        bucket.update(f.replace("\\", "/") for f in test.file_targets)

    churn: dict[str, Churn] = {}
    for test_file, targets in targets_by_file.items():
        touched = [c for c in commits if test_file in c]
        if not touched:
            continue
        # Skapelsecommiten räknas bort: allt är nytt där, inget "lagades".
        alone = sum(1 for c in touched[:-1] if not (c & targets))
        churn[test_file] = Churn(total=len(touched), test_only=alone)
    return churn


def render_churn(churn: dict[str, Churn], findings: list[Finding], limit: int = 12) -> str:
    """Historiksektionen: testfiler som bevisligen kostat underhåll.

    Korsningen är poängen — en fil med hög ensam-churn OCH fabrikationssignaler är den
    starkaste strykkandidaten: den har kostat lagningar utan att beteendet ändrats, och
    den spikar tillstånd produktionen inte producerar."""
    rows = [(f, c) for f, c in churn.items() if c.test_only >= 2]
    if not rows:
        return "Ingen testfil har lagats upprepade gånger utan att målen ändrats."
    flagged_files = {finding.test.file for finding in findings}
    rows.sort(key=lambda fc: -fc[1].test_only)
    lines = [
        "Testfiler lagade utan att produktionsmålen ändrats (ensam-churn minst 2):",
        "",
        f"{'ensam':>6}{'totalt':>8}   fil",
    ]
    for file, c in rows[:limit]:
        marker = "  ⚠ även fabrikationssignaler" if file in flagged_files else ""
        lines.append(f"{c.test_only:>6}{c.total:>8}   {file}{marker}")
    if len(rows) > limit:
        lines.append(f"… {len(rows) - limit} till")
    return "\n".join(lines)
