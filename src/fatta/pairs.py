"""Selection and rendering of blind review pairs.

A random sample of modules says almost nothing, because CF and line count agree in most
cases. What decides which metric carries are the cases where they rank in **opposite**
order. This module extracts them, pairs them up, and renders the pairs without scores so
the reviewer cannot rationalize their way to the right answer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from itertools import combinations

from .graph import Footprint, Graph, used_names

# Below these thresholds the differences are noise rather than signal.
MIN_LOC = 4
MIN_CF = 40


@dataclass(frozen=True)
class Pair:
    crate: str
    heavier: Footprint
    """The function CF ranks as heavier."""
    lighter: Footprint
    disagrees: bool
    """True when line count ranks the pair in the opposite order from CF."""
    strength: float

    @property
    def flipped(self) -> bool:
        """Whether the heavier function is shown as B instead of A.

        Determined deterministically from the content so a pack always looks the same,
        without the order carrying information about which is which.
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
        """Which of A and B line count singles out as hardest.

        On disagreement it is by definition the one CF ranks as lighter."""
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
                # Both gaps must be large for the pair to say anything; the weaker of
                # the two therefore sets the strength.
                strength=min(cf_gap, loc_gap),
            )
        )
    return out


def pick(pool: list[Pair], count: int, used: set[str]) -> list[Pair]:
    """Selection spread across the whole strength range, each function in at most one pair.

    Purely greedy selection by strength yields only the extremes, and they are their own
    kind of code: short delegating wrappers with enormous closures. A couple of those
    belong in the pack, but twelve make it a test of wrappers rather than of
    disagreement. The pool is therefore split into as many bands as pairs to pick, and
    the strongest available is taken from each band.
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


def contract_block(crate: Graph, item_id: str) -> str:
    """The contract neighborhood, sorted by name.

    The sort is deliberately alphabetical rather than by size — size order would leak
    exactly the metric that must stay hidden.
    """
    used = used_names(crate.body_text(item_id)) if crate.use_directed else None
    deps = sorted(
        (dep for dep in crate.closure(item_id, used) if not crate.is_free(dep)),
        key=crate.name_of,
    )
    texts = [t for t in (crate.contract_text(dep, used) for dep in deps) if t]
    if not texts:
        return "_No local dependencies — everything in the signature is well known._"
    return "```rust\n" + "\n\n".join(texts) + "\n```"


def render_pair(crate: Graph, pair: Pair, number: int) -> str:
    first, second = pair.as_shown()
    lines = [
        f"# Pair {number:02d} — {pair.crate}",
        "",
        "Which of A and B would be hardest to reimplement correctly from scratch, given",
        "only its signature and the contract neighborhood below?",
        "",
        "Answer A or B in the review sheet. Do not open the answer key until every pair",
        "is answered.",
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
            f"### Contract neighborhood for {label}",
            "",
            contract_block(crate, footprint.item_id),
            "",
        ]
    return "\n".join(lines)


def render_sheet(pairs: list[tuple[int, Pair]]) -> str:
    lines = [
        "# Review sheet",
        "",
        "Fill in one answer per pair before opening the answer key. Write A or B.",
        "",
        "| Pair | Crate | Your answer |",
        "|---|---|---|",
    ]
    lines += [f"| {n:02d} | {p.crate} | |" for n, p in pairs]
    lines += [
        "",
        "## Protocol",
        "",
        "The question is which function would be hardest to **reimplement correctly**",
        "given only the signature and the contract neighborhood — not which is longest,",
        "prettiest, or most intricate to read line by line.",
        "",
        "The pairs are chosen where CF and line count rank in opposite order, plus a few",
        "control pairs where they agree. The controls catch random answering: if they too",
        "land around half right, neither metric carries, and the disagreements say",
        "nothing either.",
        "",
        "Evaluate with `fatta score review/facit.json <your answers>`.",
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
