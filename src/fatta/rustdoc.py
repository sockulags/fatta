"""Frontend för Rust: bygger en språkneutral graf ur rustdoc-JSON.

Generera indata med (kräver nightly):

    cargo rustdoc --lib -- -Zunstable-options --output-format json --document-private-items
"""

from __future__ import annotations

import re
from pathlib import Path

from .graph import FUNCTION, MEMBER, TYPE, Graph, Item

TYPE_KINDS = ("struct", "enum", "union", "trait")
MEMBER_KINDS = ("struct_field", "variant")

# Ett utdrag som verkligen är skriven kod. Derive-genererade metoder får spans som pekar
# på `#[derive(...)]`-raden, och blanket-impls från std har spans i källor vi inte kan
# läsa — bägge saknar därför en fn-deklaration och ska inte mätas som kod.
_FN_START = re.compile(
    r"^\s*(pub\s*(\([^)]*\)\s*)?)?(default\s+)?(const\s+)?(async\s+)?"
    r"(unsafe\s+)?(extern\s+\"[^\"]*\"\s+)?fn\b"
)


def signature_only(src: str) -> str:
    """Klipper vid kroppens början — den första klammern på djup noll.

    Pilen i `-> T` innehåller ett `>` som inte stänger någon vinkelparentes; räknas det
    som stängning blir djupet negativt och kroppen följer med in i kontraktet."""
    depth = 0
    previous = ""
    for index, char in enumerate(src):
        if char in "(<[":
            depth += 1
        elif char in ")]" or (char == ">" and previous not in "-="):
            depth = max(0, depth - 1)
        elif char == "{" and depth == 0:
            return src[:index].rstrip()
        previous = char
    return src


def kind_of(item: dict) -> str:
    return next(iter(item.get("inner") or {}), "")


def member_ids(inner: dict) -> list:
    kind = inner.get("kind")
    if isinstance(kind, dict):
        if "plain" in kind:
            return kind["plain"].get("fields", [])
        if "tuple" in kind:
            return [f for f in kind["tuple"] if f is not None]
    return inner.get("variants", []) or inner.get("fields", []) or []


def type_refs(node: object) -> set[str]:
    """Alla item-id:n ett typträd refererar till.

    Rustdoc märker upplösta typreferenser som objekt med både `id` och `path`. Stabilt
    över de formatversioner vi sett, men det är en heuristik."""
    found: set[str] = set()
    stack: list[object] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if "path" in current and isinstance(current.get("id"), (int, str)):
                found.add(str(current["id"]))
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return found


class _Source:
    """Källtext utklippt ur items spans."""

    def __init__(self, root: Path):
        self.root = root
        self._cache: dict[str, list[str]] = {}

    def lines(self, filename: str) -> list[str]:
        if filename not in self._cache:
            path = Path(filename)
            if not path.is_absolute():
                path = self.root / filename
            try:
                self._cache[filename] = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                self._cache[filename] = []
        return self._cache[filename]

    def of(self, item: dict) -> str:
        """Rustdoc räknar rad och kolumn från ett, och slutkolumnen är exklusiv. Utan
        kolumnkorrigeringen tappar varje utdrag sitt första tecken."""
        span = item.get("span")
        if not span:
            return ""
        lines = self.lines(span["filename"])
        if not lines:
            return ""
        (begin_line, begin_col), (end_line, end_col) = span["begin"], span["end"]
        chunk = list(lines[begin_line - 1 : end_line])
        if not chunk:
            return ""
        start, stop = max(0, begin_col - 1), max(0, end_col - 1)
        if len(chunk) == 1:
            return chunk[0][start:stop]
        chunk[0] = chunk[0][start:]
        chunk[-1] = chunk[-1][:stop]
        return "\n".join(chunk)


def crate_name(doc: dict) -> str:
    root = doc["index"].get(str(doc["root"])) or {}
    return root.get("name") or "?"


def load(doc: dict, src_root: Path, include_docs: bool = True, **graph_args) -> Graph:
    index = {str(k): v for k, v in doc["index"].items()}
    paths = {str(k): v for k, v in doc["paths"].items()}
    externs = {str(k): v["name"] for k, v in (doc.get("external_crates") or {}).items()}
    source = _Source(src_root)

    def origin(item_id: str) -> str | None:
        """None betyder lokal. Metoder i impl-block saknas i `paths` — bara namngivna
        sökvägar hamnar där — så ett item i `index` utan sökväg är lokalt, inte okänt.
        Utan den regeln försvinner merparten av all riktig kod ur mätningen."""
        entry = paths.get(item_id)
        if entry is None:
            return None if item_id in index else "?"
        crate_id = str(entry.get("crate_id", 0))
        return None if crate_id == "0" else externs.get(crate_id, "?")

    # Mottagartypen står bara som `Self` i signaturen och måste hämtas ur impl-blocket.
    owners: dict[str, set[str]] = {}
    for item in index.values():
        if kind_of(item) != "impl":
            continue
        impl = item["inner"]["impl"]
        if impl.get("is_synthetic"):
            continue
        refs = type_refs(impl.get("for"))
        for member in impl.get("items", []):
            owners.setdefault(str(member), set()).update(refs)

    def doc_of(item: dict) -> str:
        return (item.get("docs") or "") if include_docs else ""

    # Vad en kropp anropar syns inte i rustdoc-JSON — där finns inga kroppar. Namnen
    # matchas därför mot källtexten, vilket är grövre än tsc:s upplösning: två items med
    # samma namn går inte att skilja åt. Överskattning är det säkrare felet, men
    # asymmetrin mot TypeScript-frontenden är verklig och värd att känna till.
    by_name: dict[str, list[str]] = {}
    for candidate, raw in index.items():
        name = raw.get("name")
        if name and origin(candidate) is None:
            by_name.setdefault(name, []).append(candidate)

    def calls_in(body: str, own_id: str) -> tuple[str, ...]:
        found: set[str] = set()
        for word in set(re.findall(r"\b[A-Za-z_]\w*\b", body)):
            for candidate in by_name.get(word, ()):
                if candidate != own_id:
                    found.add(candidate)
        return tuple(sorted(found))

    items: dict[str, Item] = {}
    for item_id, raw in index.items():
        kind = kind_of(raw)
        name = raw.get("name") or ""
        src = source.of(raw)
        span = raw.get("span") or {}
        common = {
            "id": item_id,
            "name": name,
            "external": origin(item_id),
            "file": span.get("filename", ""),
            "line": (span.get("begin") or [0])[0],
        }

        if kind == "function":
            if not _FN_START.match(src):
                continue  # genererat eller oläsbart, inte skriven kod
            items[item_id] = Item(
                kind=FUNCTION,
                contract=f"{doc_of(raw)}\n{signature_only(src)}".strip(),
                body=src,
                refs=tuple(sorted(type_refs(raw["inner"]["function"].get("sig")))),
                calls=calls_in(src, item_id),
                owner=tuple(sorted(owners.get(item_id, set()))),
                **common,
            )
        elif kind in TYPE_KINDS:
            inner = raw["inner"][kind]
            members = (
                [str(m) for m in inner.get("items", [])]
                if kind == "trait"
                else [str(m) for m in member_ids(inner)]
            )
            items[item_id] = Item(
                kind=TYPE,
                contract=f"{doc_of(raw)}\n{signature_only(src)}".strip(),
                members=tuple(members),
                **common,
            )
        elif kind in MEMBER_KINDS:
            items[item_id] = Item(
                kind=MEMBER,
                contract=src,
                refs=tuple(sorted(type_refs(raw.get("inner")))),
                **common,
            )
        elif kind in ("type_alias", "constant", "static"):
            items[item_id] = Item(
                kind=TYPE,
                contract=f"{doc_of(raw)}\n{src}".strip(),
                refs=tuple(sorted(type_refs(raw.get("inner")))),
                **common,
            )

    # Externa items som bara nämns i `paths` — vi kan inte se deras kontrakt, men vi
    # måste veta att de finns för att kunna avgöra om de är gratis.
    for item_id, entry in paths.items():
        if item_id in items:
            continue
        crate_id = str(entry.get("crate_id", 0))
        if crate_id == "0":
            continue
        items[item_id] = Item(
            id=item_id,
            name="::".join(entry.get("path", [])) or item_id,
            kind=TYPE,
            contract="",
            external=externs.get(crate_id, "?"),
        )

    # Ett trait-item bär sina metoder som medlemmar; de metoderna är funktioner, och
    # deras kontrakt är signaturen. Det gör att en anropare som bara rör en metod bara
    # betalar för den.
    return Graph(name=crate_name(doc), items=items, **graph_args)
