"""Answer-key tests against the probe crate in probes/cfprobe.

The fixture is generated rustdoc JSON and is checked in, so the tests run without a Rust
toolchain. Regenerate with scripts/regen-fixture.sh when the probe crate changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fatta import rustdoc
from fatta.graph import Graph
from fatta.rustdoc import signature_only

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "cfprobe.json"
PROBE_SRC = REPO / "probes" / "cfprobe"


def build(include_docs: bool = True, use_directed: bool = True) -> Graph:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return rustdoc.load(
        doc,
        src_root=PROBE_SRC,
        include_docs=include_docs,
        use_directed=use_directed,
    )


@pytest.fixture
def crate() -> Graph:
    return build()


@pytest.fixture
def crate_whole() -> Graph:
    """The metric as it looked before the usage-directed fix."""
    return build(use_directed=False)


def find(crate: Graph, name: str) -> str:
    for item_id in crate.local_functions():
        if crate.name_of(item_id) == name:
            return item_id
    raise AssertionError(f"hittade inte funktionen {name}")


def test_inversionen_mot_radantal(crate: Graph) -> None:
    """The core claim: a short function can have a larger footprint than a long one."""
    run = crate.footprint(find(crate, "run"))
    checksum = crate.footprint(find(crate, "checksum"))

    assert run.loc < checksum.loc, "run should be the shorter function"
    assert run.cf > checksum.cf, "but have the larger footprint"


def test_std_kostar_ingenting(crate: Graph) -> None:
    """checksum touches only std in its signature, so the closure should be free."""
    checksum = crate.footprint(find(crate, "checksum"))

    assert checksum.closure_tokens == 0
    assert checksum.charged == ()
    assert checksum.cf == checksum.body_tokens


def test_slutningen_ar_transitiv(crate: Graph) -> None:
    """run touches Config directly, and Limits transitively via the cfg.limits field."""
    names = {name for name, _ in crate.footprint(find(crate, "run")).charged}

    assert {"Config", "Report"} <= names, "direct references missing"
    assert "Limits" in names, "transitive reference via a used field missing"


def test_oanvanda_falt_dras_inte_in(crate: Graph) -> None:
    """run reads cfg.limits and cfg.name but never cfg.stage, so Stage does not belong
    in what one must understand to write run."""
    names = {name for name, _ in crate.footprint(find(crate, "run")).charged}

    assert "Stage" not in names


def test_hela_typer_drar_in_allt(crate_whole: Graph) -> None:
    """With --whole-types the metric falls back to charging whole definitions."""
    names = {name for name, _ in crate_whole.footprint(find(crate_whole, "run")).charged}

    assert {"Config", "Limits", "Report", "Stage"} <= names


def test_bred_typ_kostar_bara_det_som_lases(crate: Graph, crate_whole: Graph) -> None:
    """peek opens a ten-field record but reads one."""
    smalt = crate.footprint(find(crate, "peek"))
    brett = crate_whole.footprint(find(crate_whole, "peek"))

    assert smalt.closure_tokens < brett.closure_tokens / 2


def test_vidarebefordran_oppnar_ingenting(crate: Graph) -> None:
    """forward passes the record along without touching a single field. Carrying it
    costs; understanding its insides does not — the wrapper finding that forced the fix."""
    forward = crate.footprint(find(crate, "forward"))
    peek = crate.footprint(find(crate, "peek"))

    assert forward.closure_tokens < peek.closure_tokens


def test_kontrakt_utesluter_kroppen(crate: Graph) -> None:
    """A dependency contract must never contain its implementation."""
    contract = crate.contract_text(find(crate, "checksum"))

    assert "fn checksum" in contract
    assert "wrapping_mul" not in contract, "the body leaked into the contract"


def test_egen_kropp_raknas(crate: Graph) -> None:
    """The measured function own body, however, is part of CF."""
    body = crate.body_text(find(crate, "checksum"))

    assert "wrapping_mul" in body


def test_utdraget_borjar_och_slutar_ratt(crate: Graph) -> None:
    """Spans are one-based in the column. Matching on substrings alone hides a dropped
    first character, so the edges are tested explicitly."""
    body = crate.body_text(find(crate, "checksum"))

    assert body.startswith("pub fn checksum"), body[:40]
    assert body.rstrip().endswith("}"), body[-40:]


def test_doc_paverkar_matningen() -> None:
    """Doc comments in dependency contracts are an open design question — they must be
    switchable, and the switch must show in the number."""
    med_doc = build(include_docs=True)
    utan_doc = build(include_docs=False)

    a = med_doc.footprint(find(med_doc, "run"))
    b = utan_doc.footprint(find(utan_doc, "run"))

    assert b.closure_tokens < a.closure_tokens
    assert b.body_tokens == a.body_tokens, "the body should be unaffected"


def test_signature_only_klipper_vid_kroppen() -> None:
    src = "pub fn f<T: Into<u8>>(x: T) -> Result<u8, ()> {\n    Ok(x.into())\n}"

    assert signature_only(src) == "pub fn f<T: Into<u8>>(x: T) -> Result<u8, ()>"


def test_signature_only_lamnar_kroppslos_signatur_orord() -> None:
    src = "fn f(x: u8) -> u8;"

    assert signature_only(src) == src


def test_alla_lokala_funktioner_hittas(crate: Graph) -> None:
    """Including methods. They are absent from rustdoc\'s `paths`, and counting them as
    unknown makes most real code vanish from the measurement."""
    names = {crate.name_of(i) for i in crate.local_functions()}

    assert names == {"run", "checksum", "peek", "forward", "depth"}


def test_metoder_mats_som_funktioner(crate: Graph) -> None:
    depth = crate.footprint(find(crate, "depth"))

    assert depth.loc > 0, "source text not found"
    assert "Limits" in {name for name, _ in depth.charged}, "self.limits was not followed"
