"""Facittester mot sondkretsen i probes/cfprobe.

Fixturen är genererad rustdoc-JSON och är incheckad, så testerna kör utan Rust-toolchain.
Regenerera med scripts/regen-fixture.sh om sondkretsen ändras.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fatta.metric import Crate, signature_only

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "cfprobe.json"
PROBE_SRC = REPO / "probes" / "cfprobe"


def build(include_docs: bool = True, use_directed: bool = True) -> Crate:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return Crate.from_doc(
        doc,
        src_root=PROBE_SRC,
        include_docs=include_docs,
        use_directed=use_directed,
    )


@pytest.fixture
def crate() -> Crate:
    return build()


@pytest.fixture
def crate_whole() -> Crate:
    """Måttet som det såg ut före den användningsstyrda lagningen."""
    return build(use_directed=False)


def find(crate: Crate, name: str) -> str:
    for item_id in crate.local_functions():
        if crate.name_of(item_id) == name:
            return item_id
    raise AssertionError(f"hittade inte funktionen {name}")


def test_inversionen_mot_radantal(crate: Crate) -> None:
    """Kärnpåståendet: kort funktion kan ha större fotavtryck än lång."""
    run = crate.footprint(find(crate, "run"))
    checksum = crate.footprint(find(crate, "checksum"))

    assert run.loc < checksum.loc, "run ska vara den kortare funktionen"
    assert run.cf > checksum.cf, "men ha det större fotavtrycket"


def test_std_kostar_ingenting(crate: Crate) -> None:
    """checksum rör bara std i signaturen, så slutningen ska vara gratis."""
    checksum = crate.footprint(find(crate, "checksum"))

    assert checksum.closure_tokens == 0
    assert checksum.charged == ()
    assert checksum.cf == checksum.body_tokens


def test_slutningen_ar_transitiv(crate: Crate) -> None:
    """run rör Config direkt, och Limits transitivt via fältet cfg.limits."""
    names = {name for name, _ in crate.footprint(find(crate, "run")).charged}

    assert {"Config", "Report"} <= names, "direkta referenser saknas"
    assert "Limits" in names, "transitiv referens via ett använt fält saknas"


def test_oanvanda_falt_dras_inte_in(crate: Crate) -> None:
    """run läser cfg.limits och cfg.name men aldrig cfg.stage, så Stage hör inte hemma
    i det man måste förstå för att skriva run."""
    names = {name for name, _ in crate.footprint(find(crate, "run")).charged}

    assert "Stage" not in names


def test_hela_typer_drar_in_allt(crate_whole: Crate) -> None:
    """Med --whole-types faller måttet tillbaka till att ladda för hela definitioner."""
    names = {name for name, _ in crate_whole.footprint(find(crate_whole, "run")).charged}

    assert {"Config", "Limits", "Report", "Stage"} <= names


def test_bred_typ_kostar_bara_det_som_lases(crate: Crate, crate_whole: Crate) -> None:
    """peek öppnar en post med tio fält men läser ett."""
    smalt = crate.footprint(find(crate, "peek"))
    brett = crate_whole.footprint(find(crate_whole, "peek"))

    assert smalt.closure_tokens < brett.closure_tokens / 2


def test_vidarebefordran_oppnar_ingenting(crate: Crate) -> None:
    """forward skickar posten vidare utan att röra ett enda fält. Att bära den kostar,
    att förstå dess inre gör det inte — och det var omslagsfyndet som krävde lagningen."""
    forward = crate.footprint(find(crate, "forward"))
    peek = crate.footprint(find(crate, "peek"))

    assert forward.closure_tokens < peek.closure_tokens


def test_kontrakt_utesluter_kroppen(crate: Crate) -> None:
    """Ett beroendes kontrakt får aldrig innehålla dess implementation."""
    contract = crate.contract_text(find(crate, "checksum"))

    assert "fn checksum" in contract
    assert "wrapping_mul" not in contract, "kroppen läckte in i kontraktet"


def test_egen_kropp_raknas(crate: Crate) -> None:
    """Den mätta funktionens egen kropp ingår däremot i CF."""
    body = crate.body_text(find(crate, "checksum"))

    assert "wrapping_mul" in body


def test_utdraget_borjar_och_slutar_ratt(crate: Crate) -> None:
    """Spans är ettbaserade i kolumn. Matchar man bara på delsträngar syns det inte att
    första tecknet fallit bort, så kanterna testas uttryckligen."""
    body = crate.body_text(find(crate, "checksum"))

    assert body.startswith("pub fn checksum"), body[:40]
    assert body.rstrip().endswith("}"), body[-40:]


def test_doc_paverkar_matningen() -> None:
    """Doc-kommentarer i beroendens kontrakt är en öppen designfråga — de ska gå att
    slå av, och det ska synas i siffran."""
    med_doc = build(include_docs=True)
    utan_doc = build(include_docs=False)

    a = med_doc.footprint(find(med_doc, "run"))
    b = utan_doc.footprint(find(utan_doc, "run"))

    assert b.closure_tokens < a.closure_tokens
    assert b.body_tokens == a.body_tokens, "kroppen ska inte påverkas"


def test_signature_only_klipper_vid_kroppen() -> None:
    src = "pub fn f<T: Into<u8>>(x: T) -> Result<u8, ()> {\n    Ok(x.into())\n}"

    assert signature_only(src) == "pub fn f<T: Into<u8>>(x: T) -> Result<u8, ()>"


def test_signature_only_lamnar_kroppslos_signatur_orord() -> None:
    src = "fn f(x: u8) -> u8;"

    assert signature_only(src) == src


def test_alla_lokala_funktioner_hittas(crate: Crate) -> None:
    """Inklusive metoder. De saknas i rustdocs `paths`, och räknas de som okända
    försvinner merparten av all riktig kod ur mätningen."""
    names = {crate.name_of(i) for i in crate.local_functions()}

    assert names == {"run", "checksum", "peek", "forward", "depth"}


def test_metoder_mats_som_funktioner(crate: Crate) -> None:
    depth = crate.footprint(find(crate, "depth"))

    assert depth.loc > 0, "källtexten hittades inte"
    assert "Limits" in {name for name, _ in depth.charged}, "self.limits följdes inte"
