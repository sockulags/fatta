"""Tester för städkön. Signalerna testas var för sig och i kombination."""

from __future__ import annotations

from fatta.graph import FUNCTION, Graph, Item
from fatta.testhealth import Churn, analyze, internal_symbols, parse_git_log, render, render_churn
from fatta.testmap import TestCase, TestMap


def make_test(**kwargs) -> TestCase:
    base = dict(
        file="a.test.ts", suite="s", name="t", line=1,
        targets=({"name": "helper", "file": "lib/helper.ts", "line": 1},),
        file_targets=(), source_reads=(), casts=(), expect_errors=0, assertions=(),
    )
    base.update(kwargs)
    return TestCase(**base)


def make_map(tests: list[TestCase]) -> TestMap:
    return TestMap(project="x", tests=tests, mocks={})


def graph_with_internal() -> Graph:
    """entry anropar helper — helper är alltså intern, entry är det inte."""
    return Graph(name="g", items={
        "e": Item(id="e", name="entry", kind=FUNCTION, contract="", body="x",
                  calls=("h",), file="app/route.ts"),
        "h": Item(id="h", name="helper", kind=FUNCTION, contract="", body="y",
                  file="lib/helper.ts"),
    })


def test_kast_flaggas_som_fabrikation() -> None:
    tm = make_map([make_test(casts=({"line": 5, "text": "x as any"},))])

    findings = analyze(tm)

    assert findings and "fabricated" in findings[0].reasons[0]


def test_kast_utan_produktionsmal_flaggas_inte() -> None:
    """Ett kast i ett test som inte rör produktionskod bevisar ingenting."""
    tm = make_map([make_test(targets=(), casts=({"line": 5, "text": "x as any"},))])

    assert analyze(tm) == []


def test_kallasare_flaggas() -> None:
    tm = make_map([make_test(source_reads=("app/page.tsx",))])

    findings = analyze(tm)

    assert findings and "source_reader" in findings[0].reasons[0]


def test_internal_symbols_ur_grafen() -> None:
    assert internal_symbols(graph_with_internal()) == {("lib/helper.ts", "helper")}


def test_vattenlinjen_flaggar_inte_ensam() -> None:
    """Att enhetstesta interna funktioner är normalt — signalen är kontext, inte dom."""
    tm = make_map([make_test()])

    assert analyze(tm, graph_with_internal()) == []


def test_vattenlinjen_laggs_till_nar_annan_signal_slagit() -> None:
    tm = make_map([make_test(casts=({"line": 1, "text": "as any"},))])

    findings = analyze(tm, graph_with_internal())

    assert any("below_waterline" in r for r in findings[0].reasons)


def test_literalspik_kraver_intern_maltavla() -> None:
    """En lång literal mot ett entrypoint är ofta ett medvetet kontrakt; samma spik
    på en intern funktion är ett kopietest."""
    assertion = ({"line": 9, "text": "expect(x).toBe('ett långt exakt felmeddelande här')"},)
    mot_intern = make_test(assertions=assertion)
    mot_entry = make_test(
        targets=({"name": "entry", "file": "app/route.ts", "line": 1},),
        assertions=assertion,
    )
    graph = graph_with_internal()

    flaggat = analyze(make_map([mot_intern]), graph)
    rent = analyze(make_map([mot_entry]), graph)

    assert any("literal_pin" in r for f in flaggat for r in f.reasons)
    assert not any("literal_pin" in r for f in rent for r in f.reasons)


def test_kort_literal_ar_inte_kopietest() -> None:
    tm = make_map([make_test(assertions=({"line": 2, "text": "expect(s).toBe('DONE')"},))])

    findings = analyze(tm, graph_with_internal())

    assert not any("literal_pin" in r for f in findings for r in f.reasons)


def test_kombination_rankas_hogst() -> None:
    varsting = make_test(
        name="värsting",
        casts=({"line": 1, "text": "as any"},),
        source_reads=("lib/helper.ts",),
    )
    mild = make_test(name="mild", source_reads=("lib/other.ts",))
    tm = make_map([mild, varsting])

    findings = analyze(tm, graph_with_internal())

    assert findings[0].test.name == "värsting"
    assert findings[0].score > findings[1].score


def test_render_summerar_kategorier() -> None:
    tm = make_map([make_test(casts=({"line": 1, "text": "as any"},))])

    text = render(analyze(tm))

    assert "fabricated" in text and "flaggade" in text


SEP = chr(1)
NL = chr(10)
GITLOG = (
    SEP + NL.join(["aaa", "x.test.ts", "lib/x.ts", ""])
    + SEP + NL.join(["bbb", "x.test.ts", ""])
    + SEP + NL.join(["ccc", "x.test.ts", ""])
    + SEP + NL.join(["ddd", "x.test.ts", "lib/x.ts", ""])
)


def test_gitlog_parsas_till_filmangder() -> None:
    commits = parse_git_log(GITLOG)

    assert len(commits) == 4
    assert commits[1] == {"x.test.ts"}


def test_ensamchurn_raknar_lagningar_utan_malandring() -> None:
    """Två commits rörde bara testet; skapelsen (äldsta) räknas bort ur ensam-churnen."""
    from unittest.mock import patch
    from types import SimpleNamespace
    from fatta.testhealth import measure_churn
    from pathlib import Path

    tm = make_map([make_test(file="x.test.ts",
                             targets=({"name": "f", "file": "lib/x.ts", "line": 1},))])
    fake = SimpleNamespace(returncode=0, stdout=GITLOG)
    with patch("fatta.testhealth.subprocess.run", return_value=fake):
        churn = measure_churn(tm, Path("."))

    assert churn["x.test.ts"].total == 4
    assert churn["x.test.ts"].test_only == 2


def test_churnrapporten_korsar_med_fabrikationssignaler() -> None:
    findings = analyze(make_map([make_test(file="x.test.ts",
                                           casts=({"line": 1, "text": "as any"},))]))
    text = render_churn({"x.test.ts": Churn(total=5, test_only=3)}, findings)

    assert "x.test.ts" in text and "fabrikationssignaler" in text


def test_lag_churn_rapporteras_inte() -> None:
    text = render_churn({"x.test.ts": Churn(total=3, test_only=1)}, [])

    assert "Ingen testfil" in text
