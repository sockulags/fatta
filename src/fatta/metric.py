"""Beräkning av förståelsefotavtryck (CF) ur rustdoc-JSON.

CF(M) = tokens(M:s egen kropp) + summan av tokens för kontraktet hos allt M:s signatur
transitivt rör vid. Beroendens *kroppar* räknas aldrig — bara deras kontrakt. Det är
måttets bärande antagande: ett kontrakt ska räcka för att förstå vad som ligger bakom.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

# Crates modellen redan kan. Deras kontrakt kostar noll — måttet är avsiktligt relativt
# läsarens förkunskaper, och listan ska vara synlig snarare än gömd.
WELLKNOWN = frozenset(
    {"std", "core", "alloc", "proc_macro", "serde", "tokio", "anyhow", "thiserror"}
)

LOCAL = "<local>"


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
    wellknown: frozenset[str] = WELLKNOWN
    count_tokens: Callable[[str], int] = estimate_tokens
    _src_cache: dict[str, list[str]] = field(default_factory=dict, repr=False)

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
        entry = self.paths.get(item_id)
        if entry is None:
            return "?"
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
        """Klipper ut ett items källtext ur dess span."""
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
        if len(chunk) == 1:
            return chunk[0][begin_col:end_col]
        chunk = list(chunk)
        chunk[0] = chunk[0][begin_col:]
        chunk[-1] = chunk[-1][:end_col]
        return "\n".join(chunk)

    # -- kontrakt kontra kropp --------------------------------------------------

    def contract_text(self, item_id: str) -> str:
        """Det en läsare måste se av ett beroende: doc plus signatur eller definition.

        Aldrig implementationen — det är hela poängen med att kalla det ett kontrakt.
        """
        item = self.index.get(item_id)
        if item is None:
            return ""
        src = self.source(item)
        if kind_of(item) == "function":
            src = signature_only(src)
        doc = (item.get("docs") or "") if self.include_docs else ""
        return f"{doc}\n{src}".strip()

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

    def surface_of(self, item_id: str) -> set[str]:
        """Vad ett items kontrakt rör vid: signaturen för funktioner, fälttyperna för
        strukturar. Aldrig kroppen — den finns inte ens i rustdoc-JSON."""
        item = self.index.get(item_id)
        if item is None:
            return set()
        inner = item.get("inner", {})
        kind = kind_of(item)
        if kind == "function":
            return self.type_refs(inner["function"].get("sig"))
        if kind in ("struct", "enum", "union"):
            out: set[str] = set()
            for child_id in member_ids(inner[kind]):
                child = self.index.get(str(child_id))
                if child is not None:
                    out |= self.type_refs(child.get("inner"))
            return out
        if kind == "trait":
            out = set()
            for member in inner["trait"].get("items", []):
                out |= self.surface_of(str(member))
            return out
        if kind in ("struct_field", "variant", "type_alias", "constant", "static"):
            return self.type_refs(inner)
        return set()

    def closure(self, root: str) -> set[str]:
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
                queue.extend(self.surface_of(cur))
        return seen

    def footprint(self, item_id: str) -> Footprint:
        item = self.index.get(item_id, {})
        body = self.body_text(item_id)
        charged: list[tuple[str, int]] = []
        free = 0
        for dep in sorted(self.closure(item_id)):
            if self.is_free(dep):
                free += 1
                continue
            tokens = self.count_tokens(self.contract_text(dep))
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

    def local_functions(self) -> Iterable[str]:
        for item_id, item in self.index.items():
            if kind_of(item) == "function" and self.crate_of(item_id) == LOCAL:
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
