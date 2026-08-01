"""Beräkning av förståelsefotavtryck (CF) ur rustdoc-JSON.

CF(M) = tokens(M:s egen kropp) + summan av tokens för kontraktet hos allt M:s signatur
transitivt rör vid. Beroendens *kroppar* räknas aldrig — bara deras kontrakt. Det är
måttets bärande antagande: ett kontrakt ska räcka för att förstå vad som ligger bakom.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

# Crates modellen redan kan. Deras kontrakt kostar noll — måttet är avsiktligt relativt
# läsarens förkunskaper, och listan ska vara synlig snarare än gömd.
WELLKNOWN = frozenset(
    {"std", "core", "alloc", "proc_macro", "serde", "tokio", "anyhow", "thiserror"}
)

LOCAL = "<local>"

# Namn en funktionskropp rör vid. Rustdoc-JSON saknar kroppar, så de här läses ur
# källtexten: fältaccesser, bindningar i strukturliteraler och segment i sökvägar.
# Heuristiken är avsiktligt frikostig — att ta med för mycket överskattar kostnaden,
# att missa något underskattar den, och överskattning är det säkrare felet.
_ACCESS = re.compile(r"\.\s*([A-Za-z_]\w*)")
_BINDING = re.compile(r"\b([A-Za-z_]\w*)\s*:")
_PATH_SEGMENT = re.compile(r"::\s*([A-Za-z_]\w*)")


# Ett utdrag som verkligen är en skriven funktion. Derive-genererade metoder får spans
# som pekar på `#[derive(...)]`-raden, och blanket-impls från std har spans i källor vi
# inte kan läsa — bägge saknar därför en fn-deklaration och ska inte mätas som kod.
_FN_START = re.compile(
    r"^\s*(pub\s*(\([^)]*\)\s*)?)?(default\s+)?(const\s+)?(async\s+)?"
    r"(unsafe\s+)?(extern\s+\"[^\"]*\"\s+)?fn\b"
)


def used_names(body: str) -> set[str]:
    """Vilka medlemmar en kropp faktiskt nämner."""
    return (
        set(_ACCESS.findall(body))
        | set(_BINDING.findall(body))
        | set(_PATH_SEGMENT.findall(body))
    )


def estimate_tokens(text: str) -> int:
    """Grov teckenbaserad uppskattning.

    Räcker för rangordning, vilket är allt v0 behöver. Byt mot en riktig tokenizer
    (Anthropics count_tokens) innan absoluta gränsvärden publiceras.
    """
    return max(1, round(len(text) / 3.6)) if text else 0


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
class Crate:
    """En inläst rustdoc-JSON med källtextsupplösning."""

    index: dict[str, dict]
    paths: dict[str, dict]
    externs: dict[str, str]
    src_root: Path
    include_docs: bool = True
    use_directed: bool = True
    """Ladda bara för de medlemmar koden faktiskt rör.

    Med hela typdefinitioner straffas breda strukturer systematiskt, och en funktion som
    bara skickar ett värde vidare får betala för att förstå något den aldrig öppnar."""
    wellknown: frozenset[str] = WELLKNOWN
    count_tokens: Callable[[str], int] = estimate_tokens
    weigh: Callable[[str, str, str], float] | None = None
    """Vikt per kontrakt efter hur oväntat det är, som `(namn, sort, text) -> [0, 1]`.

    Utan viktning räknas ren storlek, vilket behandlar ett självklart kontrakt som lika
    dyrt som ett obegripligt. Se `surprisal`."""
    _src_cache: dict[str, list[str]] = field(default_factory=dict, repr=False)
    _owners: dict[str, set[str]] | None = field(default=None, repr=False)

    @classmethod
    def from_doc(cls, doc: dict, src_root: Path, **kwargs) -> Crate:
        return cls(
            index={str(k): v for k, v in doc["index"].items()},
            paths={str(k): v for k, v in doc["paths"].items()},
            externs={
                str(k): v["name"] for k, v in (doc.get("external_crates") or {}).items()
            },
            src_root=src_root,
            **kwargs,
        )

    # -- härkomst ---------------------------------------------------------------

    def crate_of(self, item_id: str) -> str:
        """Vilket crate ett item kommer från.

        Metoder i impl-block saknas i `paths` — bara namngivna sökvägar hamnar där. Ett
        item som finns i `index` men inte i `paths` är därför lokalt, inte okänt. Utan den
        regeln försvinner merparten av all riktig kod ur mätningen.
        """
        entry = self.paths.get(item_id)
        if entry is None:
            return LOCAL if item_id in self.index else "?"
        crate_id = str(entry.get("crate_id", 0))
        return LOCAL if crate_id == "0" else self.externs.get(crate_id, "?")

    def is_free(self, item_id: str) -> bool:
        return self.crate_of(item_id) in self.wellknown

    # -- källtext ---------------------------------------------------------------

    def _lines(self, filename: str) -> list[str]:
        if filename not in self._src_cache:
            path = Path(filename)
            if not path.is_absolute():
                path = self.src_root / filename
            try:
                self._src_cache[filename] = path.read_text(
                    encoding="utf-8"
                ).splitlines()
            except OSError:
                self._src_cache[filename] = []
        return self._src_cache[filename]

    def source(self, item: dict) -> str:
        """Klipper ut ett items källtext ur dess span.

        Rustdoc räknar både rad och kolumn från ett, och slutkolumnen är exklusiv. Utan
        kolumnkorrigeringen tappar varje utdrag sitt första tecken.
        """
        span = item.get("span")
        if not span:
            return ""
        lines = self._lines(span["filename"])
        if not lines:
            return ""
        (begin_line, begin_col), (end_line, end_col) = span["begin"], span["end"]
        chunk = lines[begin_line - 1 : end_line]
        if not chunk:
            return ""
        start, stop = max(0, begin_col - 1), max(0, end_col - 1)
        if len(chunk) == 1:
            return chunk[0][start:stop]
        chunk = list(chunk)
        chunk[0] = chunk[0][start:]
        chunk[-1] = chunk[-1][:stop]
        return "\n".join(chunk)

    # -- kontrakt kontra kropp --------------------------------------------------

    def contract_text(self, item_id: str, used: set[str] | None = None) -> str:
        """Det en läsare måste se av ett beroende: doc plus signatur eller definition.

        Aldrig implementationen — det är hela poängen med att kalla det ett kontrakt.

        Är mätningen användningsstyrd projiceras typer ner till sitt huvud plus de
        medlemmar som faktiskt nämns. En bred struktur man rör tre fält i kostar tre fält,
        inte trehundra.
        """
        item = self.index.get(item_id)
        if item is None:
            return ""
        kind = kind_of(item)
        if kind == "function":
            src = signature_only(self.source(item))
        elif used is not None and kind in ("struct", "enum", "union"):
            src = self.projected_type(item_id, used)
        else:
            src = self.source(item)
        doc = (item.get("docs") or "") if self.include_docs else ""
        return f"{doc}\n{src}".strip()

    def projected_type(self, item_id: str, used: set[str]) -> str:
        """Typens huvud plus bara de medlemmar som nämnts."""
        item = self.index[item_id]
        header = signature_only(self.source(item))
        members = [
            self.source(self.index[member])
            for member in self.members(item_id, used)
            if member in self.index
        ]
        if not members:
            return header
        return header + " { " + "; ".join(members) + " }"

    def members(self, item_id: str, used: set[str] | None) -> list[str]:
        """Fält- eller variant-id:n för en typ, filtrerade på användning."""
        item = self.index.get(item_id)
        if item is None:
            return []
        kind = kind_of(item)
        if kind not in ("struct", "enum", "union"):
            return []
        ids = [str(member) for member in member_ids(item["inner"][kind])]
        if used is None:
            return ids
        return [member for member in ids if self.name_of(member) in used]

    def body_text(self, item_id: str) -> str:
        item = self.index.get(item_id)
        return self.source(item) if item else ""

    # -- slutningen -------------------------------------------------------------

    @staticmethod
    def type_refs(node: object) -> set[str]:
        """Alla item-id:n ett typträd refererar till.

        Heuristik: rustdoc märker upplösta typreferenser som objekt med både `id` och
        `path`. Det är stabilt över formatversionerna vi stött på, men det är en
        heuristik och inte en garanti.
        """
        found: set[str] = set()
        stack: list[object] = [node]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                if "path" in cur and isinstance(cur.get("id"), (int, str)):
                    found.add(str(cur["id"]))
                stack.extend(cur.values())
            elif isinstance(cur, list):
                stack.extend(cur)
        return found

    def surface_of(self, item_id: str, used: set[str] | None = None) -> set[str]:
        """Vad ett items kontrakt rör vid: signaturen för funktioner, fälttyperna för
        strukturar. Aldrig kroppen — den finns inte ens i rustdoc-JSON.

        Signaturen filtreras aldrig: de typerna måste läsaren se oavsett. Det är typernas
        *inre* som beskärs till det som används.
        """
        item = self.index.get(item_id)
        if item is None:
            return set()
        inner = item.get("inner", {})
        kind = kind_of(item)
        if kind == "function":
            # `&self` står i JSON bara som `Self` utan id, så mottagartypen måste hämtas
            # från impl-blocket. Utan den läser en metod som om den inte hade någon typ.
            return self.type_refs(inner["function"].get("sig")) | self.owner_of(item_id)
        if kind in ("struct", "enum", "union"):
            out: set[str] = set()
            for member in self.members(item_id, used):
                child = self.index.get(member)
                if child is not None:
                    out |= self.type_refs(child.get("inner"))
            return out
        if kind == "trait":
            out = set()
            for member in inner["trait"].get("items", []):
                out |= self.surface_of(str(member), used)
            return out
        if kind in ("struct_field", "variant", "type_alias", "constant", "static"):
            return self.type_refs(inner)
        return set()

    def closure(self, root: str, used: set[str] | None = None) -> set[str]:
        """Transitiv kontraktsslutning. Gratis-items avslutar vandringen: kan läsaren
        redan typen behöver hen inte heller dess inre."""
        seen: set[str] = set()
        queue = list(self.surface_of(root))
        while queue:
            cur = queue.pop()
            if cur in seen or cur == root:
                continue
            seen.add(cur)
            if not self.is_free(cur):
                queue.extend(self.surface_of(cur, used))
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
                item = self.index.get(dep, {})
                tokens = round(
                    tokens * self.weigh(self.name_of(dep), kind_of(item), contract)
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

    def name_of(self, item_id: str) -> str:
        item = self.index.get(item_id)
        if item and item.get("name"):
            return item["name"]
        entry = self.paths.get(item_id)
        if entry and entry.get("path"):
            return "::".join(entry["path"])
        return f"#{item_id}"

    def owner_of(self, item_id: str) -> set[str]:
        """Typen en metod hänger på, hämtad ur dess impl-block."""
        if self._owners is None:
            owners: dict[str, set[str]] = {}
            for candidate, item in self.index.items():
                if kind_of(item) != "impl":
                    continue
                impl = item["inner"]["impl"]
                if impl.get("is_synthetic"):
                    continue
                refs = self.type_refs(impl.get("for"))
                for member in impl.get("items", []):
                    owners.setdefault(str(member), set()).update(refs)
            self._owners = owners
        return self._owners.get(item_id, set())

    def is_written_function(self, item_id: str) -> bool:
        """Om utdraget verkligen är en skriven funktion och inte något genererat."""
        item = self.index.get(item_id)
        if item is None or kind_of(item) != "function":
            return False
        return bool(_FN_START.match(self.source(item)))

    def local_functions(self) -> Iterable[str]:
        for item_id, item in self.index.items():
            if kind_of(item) != "function" or self.crate_of(item_id) != LOCAL:
                continue
            if self.is_written_function(item_id):
                yield item_id


def kind_of(item: dict) -> str:
    return next(iter(item.get("inner") or {}), "")


def member_ids(inner: dict) -> list:
    """Fält- eller variant-id:n för en struct/enum/union."""
    kind = inner.get("kind")
    if isinstance(kind, dict):
        if "plain" in kind:
            return kind["plain"].get("fields", [])
        if "tuple" in kind:
            return [f for f in kind["tuple"] if f is not None]
    return inner.get("variants", []) or inner.get("fields", []) or []


def signature_only(src: str) -> str:
    """Klipper en funktion vid kroppens början — den första klammern på djup noll.

    Pilen i `-> T` innehåller ett `>` som inte stänger någon vinkelparentes; räknas det
    som stängning blir djupet negativt och kroppen följer med in i kontraktet.
    """
    depth = 0
    prev = ""
    for i, ch in enumerate(src):
        if ch in "(<[":
            depth += 1
        elif ch in ")]" or (ch == ">" and prev not in "-="):
            depth = max(0, depth - 1)
        elif ch == "{" and depth == 0:
            return src[:i].rstrip()
        prev = ch
    return src
