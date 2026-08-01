"""Urval och rendering av blinda granskningspar.

Ett slumpurval av moduler säger nästan ingenting, eftersom CF och radantal är överens i de
flesta fall. Det som avgör vilket mått som bär är fallen där de rankar **tvärtom**. Modulen
plockar fram dem, parar ihop dem, och renderar paren utan poäng så att bedömaren inte kan
rationalisera fram rätt svar.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from itertools import combinations

from .metric import Crate, Footprint

# Under dessa gränser är skillnaderna brus snarare än signal.
MIN_LOC = 4
MIN_CF = 40


@dataclass(frozen=True)
class Pair:
    crate: str
    heavier: Footprint
    """Den funktion CF rankar som tyngre."""
    lighter: Footprint
    disagrees: bool
    """Sant när radantal rankar paret i motsatt ordning mot CF."""
    strength: float

    @property
    def flipped(self) -> bool:
        """Om den tyngre funktionen ska visas som B i stället för A.

        Avgörs deterministiskt av innehållet så att en pack alltid ser likadan ut, men
        utan att ordningen bär information om vilken som är vilken.
        """
        seed = f"{self.crate}:{self.heavier.name}:{self.lighter.name}".encode()
        return hashlib.sha256(seed).digest()[0] % 2 == 1

    def as_shown(self) -> tuple[Footprint, Footprint]:
        return (
            (self.lighter, self.heavier) if self.flipped else (self.heavier, self.lighter)
        )

    def heavier_label(self) -> str:
        return "B" if self.flipped else "A"

    def loc_label(self) -> str:
        """Vilken av A och B radantal pekar ut som svårast.

        Vid oenighet är det per definition den CF rankar som lättare."""
        return other_label(self.heavier_label()) if self.disagrees else self.heavier_label()


def other_label(label: str) -> str:
    return "B" if label == "A" else "A"


def relative_gap(hi: float, lo: float) -> float:
    return (hi - lo) / hi if hi > 0 else 0.0


def candidates(crate_name: str, footprints: list[Footprint]) -> list[Pair]:
    eligible = [f for f in footprints if f.loc >= MIN_LOC and f.cf >= MIN_CF]
    out: list[Pair] = []
    for a, b in combinations(eligible, 2):
        if a.cf == b.cf or a.loc == b.loc:
            continue
        heavier, lighter = (a, b) if a.cf > b.cf else (b, a)
        cf_gap = relative_gap(heavier.cf, lighter.cf)
        loc_gap = relative_gap(
            max(heavier.loc, lighter.loc), min(heavier.loc, lighter.loc)
        )
        out.append(
            Pair(
                crate=crate_name,
                heavier=heavier,
                lighter=lighter,
                disagrees=heavier.loc < lighter.loc,
                # Båda gapen måste vara stora för att paret ska säga något; det svagaste
                # av dem sätter därför styrkan.
                strength=min(cf_gap, loc_gap),
            )
        )
    return out


def pick(pool: list[Pair], count: int, used: set[str]) -> list[Pair]:
    """Urval spritt över hela styrkespannet, med varje funktion i högst ett par.

    Rent girigt urval på styrka ger bara ytterligheterna, och de är en egen sorts kod:
    korta delegerande omslag med enorm slutning. Ett par sådana hör hemma i packen, men
    tolv gör den till ett test av omslag i stället för av oenighet. Poolen delas därför i
    lika många band som par ska väljas, och det starkaste tillgängliga tas ur varje band.
    """
    ranked = sorted(pool, key=lambda p: -p.strength)
    if not ranked or count < 1:
        return []

    band_size = max(1, len(ranked) // count)
    chosen: list[Pair] = []
    for band in range(count):
        start = band * band_size
        window = ranked[start : start + band_size] if band < count - 1 else ranked[start:]
        for pair in window:
            names = {pair.heavier.name, pair.lighter.name}
            if names & used:
                continue
            used |= names
            chosen.append(pair)
            break
    return chosen


def select(
    crate_name: str,
    footprints: list[Footprint],
    n_disagree: int,
    n_agree: int,
) -> list[Pair]:
    pool = candidates(crate_name, footprints)
    used: set[str] = set()
    disagreeing = pick([p for p in pool if p.disagrees], n_disagree, used)
    agreeing = pick([p for p in pool if not p.disagrees], n_agree, used)
    return disagreeing + agreeing


# -- rendering ------------------------------------------------------------------


def contract_block(crate: Crate, item_id: str) -> str:
    """Kontraktsgrannskapet, sorterat på namn.

    Sorteringen är medvetet alfabetisk och inte på storlek — storleksordning skulle läcka
    just det måttet som ska hållas dolt.
    """
    deps = sorted(
        (dep for dep in crate.closure(item_id) if not crate.is_free(dep)),
        key=crate.name_of,
    )
    texts = [t for t in (crate.contract_text(dep) for dep in deps) if t]
    if not texts:
        return "_Inga lokala beroenden — allt i signaturen är välkänt._"
    return "```rust\n" + "\n\n".join(texts) + "\n```"


def render_pair(crate: Crate, pair: Pair, number: int) -> str:
    first, second = pair.as_shown()
    lines = [
        f"# Par {number:02d} — {pair.crate}",
        "",
        "Vilken av A och B skulle vara svårast att skriva om korrekt från grunden, om du",
        "bara hade dess signatur och kontraktsgrannskapet nedan att gå på?",
        "",
        "Svara A eller B i granskningsarket. Titta inte i `facit.json` förrän alla par är",
        "besvarade.",
        "",
    ]
    for label, footprint in (("A", first), ("B", second)):
        lines += [
            f"## {label}",
            "",
            "```rust",
            crate.body_text(footprint.item_id),
            "```",
            "",
            f"### Kontraktsgrannskap för {label}",
            "",
            contract_block(crate, footprint.item_id),
            "",
        ]
    return "\n".join(lines)


def render_sheet(pairs: list[tuple[int, Pair]]) -> str:
    lines = [
        "# Granskningsark",
        "",
        "Fyll i ett svar per par innan du öppnar facit. Skriv A eller B.",
        "",
        "| Par | Crate | Ditt svar |",
        "|---|---|---|",
    ]
    lines += [f"| {n:02d} | {p.crate} | |" for n, p in pairs]
    lines += [
        "",
        "## Protokoll",
        "",
        "Frågan är vilken funktion som vore svårast att **skriva om korrekt** givet bara",
        "signaturen och kontraktsgrannskapet — inte vilken som är längst, snyggast eller",
        "mest komplicerad att läsa rad för rad.",
        "",
        "Paren är valda där CF och radantal rankar tvärtom, plus några kontrollpar där de",
        "är överens. Kontrollerna finns för att fånga om svaren är slumpmässiga: är även de",
        "ungefär hälften rätt bär inget av måtten, och då säger oenigheterna inget heller.",
        "",
        "Utvärdera med `fatta score granskning/facit.json <dina svar>`.",
    ]
    return "\n".join(lines)


def key_entry(number: int, pair: Pair) -> dict:
    return {
        "par": number,
        "crate": pair.crate,
        "svar_cf": pair.heavier_label(),
        "svar_loc": pair.loc_label(),
        "oenigt": pair.disagrees,
        "styrka": round(pair.strength, 3),
        "tyngre": {
            "namn": pair.heavier.name,
            "cf": pair.heavier.cf,
            "loc": pair.heavier.loc,
        },
        "lattare": {
            "namn": pair.lighter.name,
            "cf": pair.lighter.cf,
            "loc": pair.lighter.loc,
        },
    }
