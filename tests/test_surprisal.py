"""Tester för överraskningsviktningen. Ingen modell körs — predictorn är en attrapp."""

from __future__ import annotations

import json

import pytest

from fatta.surprisal import Weighing, build_prompt, containment, fixed, tokens_of


def echo(text: str):
    """Predictor som alltid gissar exakt `text`."""
    return lambda _prompt: text


def test_perfekt_gissning_ger_golvvikt() -> None:
    contract = "pub fn len(&self) -> usize"
    weighing = Weighing(predictor=echo(contract), floor=0.15)

    assert weighing.weight("len", "function", contract) == pytest.approx(0.15)


def test_helt_missad_gissning_ger_full_vikt() -> None:
    weighing = Weighing(predictor=echo("something entirely different"), floor=0.15)

    weight = weighing.weight("process", "function", "pub fn process(mode: u8) -> Code")

    assert weight == pytest.approx(1.0)


def test_delvis_traff_hamnar_emellan() -> None:
    weighing = Weighing(predictor=echo("pub fn len(&self) -> u32"), floor=0.15)

    weight = weighing.weight("len", "function", "pub fn len(&self) -> usize")

    assert 0.15 < weight < 1.0


def test_containment_fragar_om_det_verkliga_forutsags() -> None:
    """Att gissa brett ska inte straffas — en läsare som redan övervägt fler
    möjligheter blir inte överraskad."""
    brett = containment("fn len(&self) -> usize", "fn len(&self) -> usize or isize or u8")
    smalt = containment("fn len(&self) -> usize", "fn len")

    assert brett == pytest.approx(1.0)
    assert smalt < 1.0


def test_tomt_kontrakt_kostar_full_vikt() -> None:
    weighing = Weighing(predictor=echo("whatever"), floor=0.15)

    assert weighing.weight("x", "function", "   ") == 1.0


def test_trasig_predictor_ger_full_vikt_och_raknas() -> None:
    """Ett tyst nollresultat vore värre än inget: då hade en oåtkomlig modell sett ut
    som att all kod plötsligt blivit självklar."""

    def broken(_prompt: str) -> str:
        raise OSError("ingen modell")

    weighing = Weighing(predictor=broken)

    assert weighing.weight("x", "function", "fn x()") == 1.0
    assert weighing.failures == 1


def test_vikter_cachas_och_overlever_omstart(tmp_path) -> None:
    path = tmp_path / "cache.json"
    contract = "pub fn len(&self) -> usize"

    first = Weighing(predictor=echo(contract), cache_path=path)
    value = first.weight("len", "function", contract)
    first.save()

    def explode(_prompt: str) -> str:
        raise AssertionError("modellen skulle inte behöva frågas igen")

    second = Weighing(predictor=explode, cache_path=path)

    assert second.weight("len", "function", contract) == pytest.approx(value)
    assert json.loads(path.read_text(encoding="utf-8"))


def test_prompten_avslojar_inte_kontraktet() -> None:
    """Ges kontraktet bort i frågan mäter man ingenting."""
    prompt = build_prompt("parse_config", "function", "cfprobe")

    assert "parse_config" in prompt and "cfprobe" in prompt
    assert "->" not in prompt, "en signatur läckte in i frågan"


def test_fixed_ar_en_av_knapp() -> None:
    assert fixed(1.0)("a", "function", "b") == 1.0


def test_tokens_ar_skiftlagesokansliga() -> None:
    assert tokens_of("Foo BAR") == {"foo", "bar"}
