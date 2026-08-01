"""Tester för urval, blindning och poängsättning av granskningspar."""

from __future__ import annotations

from fatta.cli import parse_answers, round_robin
from fatta.metric import Footprint
from fatta.pairs import Pair, candidates, select


def fp(name: str, cf: int, loc: int) -> Footprint:
    """Footprint med önskad CF; kroppen bär hela siffran."""
    return Footprint(
        name=name,
        item_id=name,
        loc=loc,
        body_tokens=cf,
        closure_tokens=0,
        charged=(),
        free_count=0,
    )


def test_oenighet_upptacks() -> None:
    """Kort funktion med stort CF mot lång med litet — måtten pekar åt olika håll."""
    pool = candidates("x", [fp("kort_tung", cf=900, loc=5), fp("lang_latt", cf=100, loc=80)])

    assert len(pool) == 1
    assert pool[0].disagrees
    assert pool[0].heavier.name == "kort_tung"


def test_enighet_markeras_inte_som_oenighet() -> None:
    pool = candidates("x", [fp("stor", cf=900, loc=80), fp("liten", cf=100, loc=5)])

    assert not pool[0].disagrees


def test_styrkan_begransas_av_det_svagaste_gapet() -> None:
    """Ett par med stort CF-gap men litet radgap ska rankas lågt."""
    stort_gap = candidates("x", [fp("a", cf=1000, loc=5), fp("b", cf=100, loc=100)])[0]
    litet_gap = candidates("x", [fp("c", cf=1000, loc=48), fp("d", cf=100, loc=50)])[0]

    assert stort_gap.strength > litet_gap.strength


def test_for_sma_funktioner_utesluts() -> None:
    assert candidates("x", [fp("liten", cf=10, loc=2), fp("ok", cf=500, loc=40)]) == []


def test_varje_funktion_anvands_hogst_en_gang() -> None:
    items = [fp(f"f{i}", cf=100 * (i + 1), loc=90 - i * 10) for i in range(6)]

    chosen = select("x", items, n_disagree=3, n_agree=0)
    names = [n for p in chosen for n in (p.heavier.name, p.lighter.name)]

    assert len(names) == len(set(names))


def test_blindningen_ar_stabil_men_delar_upp_sig() -> None:
    """Samma par ska alltid renderas likadant, men ordningen får inte bära information."""
    pairs = [
        Pair("x", fp(f"tung{i}", 900, 5), fp(f"latt{i}", 100, 80), True, 0.9)
        for i in range(24)
    ]

    assert all(p.flipped == p.flipped for p in pairs), "instabil blindning"
    labels = [p.heavier_label() for p in pairs]
    assert set(labels) == {"A", "B"}, "tunga funktionen hamnar alltid på samma plats"


def test_loc_label_ar_motsatsen_vid_oenighet() -> None:
    pair = Pair("x", fp("tung", 900, 5), fp("latt", 100, 80), disagrees=True, strength=0.9)

    assert pair.loc_label() != pair.heavier_label()


def test_loc_label_sammanfaller_vid_enighet() -> None:
    pair = Pair("x", fp("tung", 900, 80), fp("latt", 100, 5), disagrees=False, strength=0.9)

    assert pair.loc_label() == pair.heavier_label()


def test_round_robin_haller_hinkarna_jamna() -> None:
    out = round_robin([["a1", "a2", "a3"], ["b1", "b2"], ["c1"]], total=4)

    assert out == ["a1", "b1", "c1", "a2"]


def test_svar_lases_ur_ifyllt_ark() -> None:
    sheet = "| Par | Crate | Ditt svar |\n|---|---|---|\n| 01 | semver | A |\n| 02 | memchr | b |\n"

    assert parse_answers(sheet) == {1: "A", 2: "B"}


def test_svar_lases_ur_bokstavsstrang() -> None:
    assert parse_answers("ABBA") == {1: "A", 2: "B", 3: "B", 4: "A"}


def test_tomt_ark_ger_inga_svar() -> None:
    sheet = "| Par | Crate | Ditt svar |\n|---|---|---|\n| 01 | semver | |\n"

    assert parse_answers(sheet) == {}


def test_urvalet_sprids_over_styrkespannet() -> None:
    """Rent girigt urval ger bara ytterligheter; banden ska ge spridning."""
    items = [fp(f"f{i}", cf=1000 - i * 30, loc=6 + i * 3) for i in range(20)]

    chosen = select("x", items, n_disagree=4, n_agree=0)
    spann = max(p.strength for p in chosen) - min(p.strength for p in chosen)

    assert len(chosen) == 4
    assert spann > 0.05, "alla valda par har nästan samma styrka"
