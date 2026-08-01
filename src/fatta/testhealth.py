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
from dataclasses import dataclass, field

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
