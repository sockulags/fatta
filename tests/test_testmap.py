"""Tests for the test map. The emitter is validated on a real codebase; this tests the logic."""

from __future__ import annotations

import pytest

from fatta.testmap import TestMap, TestCase, parse, render


def tm(tests: list[TestCase], mocks: dict | None = None) -> TestMap:
    return TestMap(project="x", tests=tests, mocks=mocks or {})


def case(file: str, name: str, targets: list[str], n_assert: int = 1) -> TestCase:
    return TestCase(
        file=file,
        suite="s",
        name=name,
        line=1,
        targets=tuple({"name": t, "file": f"lib/{t}.ts", "line": 1} for t in targets),
        file_targets=(),
        assertions=tuple({"line": i, "text": f"expect(x).toBe({i})"} for i in range(n_assert)),
    )


def test_pinning_hittar_testerna_for_en_symbol() -> None:
    karta = tm([case("a.test.ts", "t1", ["foo"]), case("b.test.ts", "t2", ["bar"])])

    assert [t.name for t in karta.pinning("foo")] == ["t1"]


def test_pinning_rankar_pa_antal_assertions() -> None:
    karta = tm([
        case("a.test.ts", "svag", ["foo"], n_assert=1),
        case("b.test.ts", "hård", ["foo"], n_assert=5),
    ])

    assert [t.name for t in karta.pinning("foo")] == ["hård", "svag"]


def test_filfilter_loser_namnkrockar() -> None:
    krock = TestCase(
        file="a.test.ts", suite="", name="t", line=1,
        targets=({"name": "GET", "file": "app/api/health/route.ts", "line": 1},),
        file_targets=(), assertions=(),
    )
    annan = TestCase(
        file="b.test.ts", suite="", name="t2", line=1,
        targets=({"name": "GET", "file": "app/api/cv/route.ts", "line": 1},),
        file_targets=(), assertions=(),
    )
    karta = tm([krock, annan])

    assert [t.file for t in karta.pinning("GET", "health")] == ["a.test.ts"]


def test_judge_files_rankar_filer_pa_antal_traffande_tester() -> None:
    karta = tm([
        case("light.test.ts", "t1", ["foo"]),
        case("heavy.test.ts", "t2", ["foo"]),
        case("heavy.test.ts", "t3", ["foo"]),
    ])

    assert karta.judge_files("foo") == ["heavy.test.ts", "light.test.ts"]


def test_otestade_symboler_pekas_ut() -> None:
    karta = tm([case("a.test.ts", "t", ["foo"])])

    assert karta.untested(["foo", "bar"]) == ["bar"]


def test_render_varnar_nar_inget_test_finns() -> None:
    text = render("bar", [], {})

    assert "unspecified" in text


def test_render_visar_mockar() -> None:
    karta = tm([case("a.test.ts", "t", ["foo"])], mocks={"a.test.ts": ["@/lib/prisma"]})
    text = render("foo", karta.pinning("foo"), karta.mocks)

    assert "@/lib/prisma" in text


def test_parse_avvisar_fel_format() -> None:
    with pytest.raises(ValueError):
        parse({"format": "nåt-annat"})


def test_kallastande_test_hittas_via_filmal() -> None:
    """A test reading the source with readFileSync never reaches the symbol — only the file."""
    lasare = TestCase(
        file="copy.test.ts", suite="", name="t", line=1,
        targets=(), file_targets=("app/skills/page.tsx",), assertions=(),
    )
    karta = tm([lasare])

    assert karta.judge_files("SkillsPage", target_file="app/skills/page.tsx") == ["copy.test.ts"]
