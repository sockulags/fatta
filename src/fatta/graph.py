"""Språkneutral kärna: en graf av items, och beräkningarna över den.

Allt som är specifikt för ett språk ligger i en frontend som bygger den här grafen —
`rustdoc` för Rust, `typescript` för TS. Beräkningarna nedan vet ingenting om något språk;
de kan bara följa kontrakt och avgöra när de får sluta följa.

Tre sorters item räcker: `function` (inklusive metoder), `type` (struct, enum, klass,
interface, alias) och `member` (fält, variant, property).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

FUNCTION = "function"
TYPE = "type"
MEMBER = "member"

# Paket vars kontrakt läsaren redan kan. Kostar noll, och avbryter vandringen: kan man
# typen behöver man inte heller dess inre.
WELLKNOWN = frozenset(
    {
        # Rust
        "std", "core", "alloc", "proc_macro", "serde", "tokio", "anyhow", "thiserror",
        # TypeScript och JS
        "typescript", "lib", "node", "@types/node", "react", "@types/react",
        "react-dom", "@types/react-dom", "next", "zod",
    }
)

_WORD = re.compile(r"[A-Za-z_]\w*")
_ACCESS = re.compile(r"\.\s*([A-Za-z_$]\w*)")
_BINDING = re.compile(r"\b([A-Za-z_$]\w*)\s*:")
_PATH_SEGMENT = re.compile(r"(?:::|\.)\s*([A-Za-z_$]\w*)")


def estimate_tokens(text: str) -> int:
    """Grov teckenbaserad uppskattning.

    Räcker för rangordning. Byt mot en riktig tokenizer innan absoluta gränsvärden
    publiceras."""
    return max(1, round(len(text) / 3.6)) if text else 0


def used_names(body: str) -> set[str]:
    """Vilka medlemmar en kropp faktiskt nämner.

    Rustdoc och tsc ger inga kroppar i strukturerad form, så det här läses ur källtexten.
    Heuristiken är avsiktligt frikostig — att ta med för mycket överskattar kostnaden, och
    överskattning är det säkrare felet."""
    return (
        set(_ACCESS.findall(body))
        | set(_BINDING.findall(body))
        | set(_PATH_SEGMENT.findall(body))
    )


@dataclass(frozen=True)
class Item:
    """Ett namngivet ting i en kodbas."""

    id: str
    name: str
    kind: str
    contract: str
    """Deklarationen: signatur för en funktion, huvudet för en typ."""
    body: str = ""
    """Implementationen. Bara funktioner har en, och den räknas bara för den funktion
    som mäts — aldrig för dess beroenden."""
    members: tuple[str, ...] = ()
    refs: tuple[str, ...] = ()
    """Item-id:n som kontraktet rör vid."""
    owner: tuple[str, ...] = ()
    """Mottagartypen för en metod. Står sällan i signaturen och måste bäras separat."""
    calls: tuple[str, ...] = ()
    """Vad kroppen anropar eller bygger.

    I Rust bär signaturen beroendena. I TypeScript, och särskilt i React, gör den inte
    det — en komponent tar inga parametrar och skapar allt internt. Utan de här kanterna
    ser sådan kod ut att sakna beroenden helt, vilket är det farligaste möjliga felet:
    mängden utges för sluten när den inte är det."""
    external: str | None = None
    file: str = ""
    line: int = 0


@dataclass(frozen=True)
class Footprint:
    name: str
    item_id: str
    loc: int
    body_tokens: int
    closure_tokens: int
    charged: tuple[tuple[str, int], ...]
    free_count: int

    @property
    def cf(self) -> int:
        return self.body_tokens + self.closure_tokens


@dataclass
class Graph:
    """Items plus de beräkningar som gör dem till ett fotavtryck."""

    name: str
    items: dict[str, Item]
    use_directed: bool = True
    wellknown: frozenset[str] = WELLKNOWN
    count_tokens: Callable[[str], int] = estimate_tokens
    weigh: Callable[[str, str, str], float] | None = None
    _closure_cache: dict[tuple[str, frozenset[str] | None], frozenset[str]] = field(
        default_factory=dict, repr=False
    )

    # -- uppslag ----------------------------------------------------------------

    def get(self, item_id: str) -> Item | None:
        return self.items.get(item_id)

    def name_of(self, item_id: str) -> str:
        item = self.items.get(item_id)
        return item.name if item else f"#{item_id}"

    def is_free(self, item_id: str) -> bool:
        item = self.items.get(item_id)
        if item is None:
            return True
        return item.external is not None and item.external in self.wellknown

    def is_local(self, item_id: str) -> bool:
        item = self.items.get(item_id)
        return item is not None and item.external is None

    # -- kontrakt ---------------------------------------------------------------

    def members_of(self, item_id: str, used: set[str] | None) -> list[str]:
        """Medlemmar av en typ, filtrerade på vad koden faktiskt rör."""
        item = self.items.get(item_id)
        if item is None or item.kind != TYPE:
            return []
        if used is None:
            return list(item.members)
        return [m for m in item.members if self.name_of(m) in used]

    def contract_text(self, item_id: str, used: set[str] | None = None) -> str:
        """Det en läsare måste se av ett beroende — aldrig dess implementation.

        Typer projiceras ner till huvudet plus de medlemmar som nämns. En bred struktur
        man rör tre fält i kostar tre fält, inte trehundra."""
        item = self.items.get(item_id)
        if item is None:
            return ""
        if item.kind != TYPE:
            return item.contract
        members = [
            self.items[m].contract for m in self.members_of(item_id, used) if m in self.items
        ]
        if not members:
            return item.contract
        return item.contract + " { " + "; ".join(members) + " }"

    def body_text(self, item_id: str) -> str:
        item = self.items.get(item_id)
        return item.body if item else ""

    # -- slutningen -------------------------------------------------------------

    def surface(
        self, item_id: str, used: set[str] | None = None, include_calls: bool = False
    ) -> set[str]:
        """Vad ett items kontrakt rör vid.

        Signaturen filtreras aldrig — de typerna måste läsaren se oavsett. Det är typernas
        *inre* som beskärs till det som används.

        `include_calls` gäller bara den funktion som mäts. Du måste känna kontraktet för
        det du själv anropar, men inte för det *de* anropar — där räcker deras kontrakt.
        Det är den regeln som håller slutningen ändlig i stället för att svälla till hela
        programmet."""
        item = self.items.get(item_id)
        if item is None:
            return set()
        if item.kind == TYPE:
            # Typens egna referenser är arv, implements och det ett alias pekar på —
            # sådant hör till typen själv och beskärs inte av användning.
            out: set[str] = set(item.refs)
            for member in self.members_of(item_id, used):
                child = self.items.get(member)
                if child is not None:
                    out |= set(child.refs)
            return out
        surface = set(item.refs) | set(item.owner)
        if include_calls:
            surface |= set(item.calls)
        return surface

    def closure(self, root: str, used: set[str] | None = None) -> set[str]:
        """Transitiv kontraktsslutning. Välkända items avbryter vandringen."""
        key = (root, frozenset(used) if used is not None else None)
        cached = self._closure_cache.get(key)
        if cached is not None:
            return set(cached)

        seen: set[str] = set()
        queue = list(self.surface(root, include_calls=True))
        while queue:
            current = queue.pop()
            if current in seen or current == root:
                continue
            seen.add(current)
            if not self.is_free(current):
                queue.extend(self.surface(current, used))

        self._closure_cache[key] = frozenset(seen)
        return seen

    def footprint(self, item_id: str) -> Footprint:
        body = self.body_text(item_id)
        used = used_names(body) if self.use_directed else None
        charged: list[tuple[str, int]] = []
        free = 0
        for dep in sorted(self.closure(item_id, used)):
            if self.is_free(dep):
                free += 1
                continue
            contract = self.contract_text(dep, used)
            tokens = self.count_tokens(contract)
            if self.weigh is not None:
                item = self.items.get(dep)
                tokens = round(
                    tokens
                    * self.weigh(self.name_of(dep), item.kind if item else "", contract)
                )
            if tokens:
                charged.append((self.name_of(dep), tokens))
        charged.sort(key=lambda pair: -pair[1])
        return Footprint(
            name=self.name_of(item_id),
            item_id=item_id,
            loc=len(body.splitlines()),
            body_tokens=self.count_tokens(body),
            closure_tokens=sum(t for _, t in charged),
            charged=tuple(charged),
            free_count=free,
        )

    def local_functions(self) -> Iterable[str]:
        for item_id, item in self.items.items():
            if item.kind == FUNCTION and item.external is None and item.body:
                yield item_id

    # -- beskärningsvärde -------------------------------------------------------

    def pruning_value(self, item_id: str) -> int:
        """Hur mycket slutning som hänger under ett item.

        Det är vad ett pålitligt kontrakt på den här platsen skulle bespara en läsare —
        alltså var det lönar sig att dokumentera. En doc djupt ner i trädet sparar nästan
        ingenting, eftersom man var tvungen att gå dit för att läsa den."""
        below = self.closure(item_id)
        return sum(
            self.count_tokens(self.contract_text(dep))
            for dep in below
            if not self.is_free(dep)
        )
