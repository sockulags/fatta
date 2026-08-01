"""Rust frontend: builds a language-neutral graph from rustdoc JSON.

Generate input with (requires nightly):

    cargo rustdoc --lib -- -Zunstable-options --output-format json --document-private-items
"""

from __future__ import annotations

import re
from pathlib import Path

from .graph import FUNCTION, MEMBER, TYPE, Graph, Item

TYPE_KINDS = ("struct", "enum", "union", "trait")
MEMBER_KINDS = ("struct_field", "variant")

# An excerpt that really is written code. Derive-generated methods get spans pointing at
# the `#[derive(...)]` line, and blanket impls from std have spans in sources we cannot
# read — neither starts with an fn declaration and neither should be measured as code.
_FN_START = re.compile(
    r"^\s*(pub\s*(\([^)]*\)\s*)?)?(default\s+)?(const\s+)?(async\s+)?"
    r"(unsafe\s+)?(extern\s+\"[^\"]*\"\s+)?fn\b"
)


def signature_only(src: str) -> str:
    """Cuts at the start of the body — the first brace at depth zero.

    The arrow in `-> T` contains a `>` that closes no angle bracket; counting it as a
    close makes the depth go negative and the body leaks into the contract."""
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
    """All item ids a type tree refers to.

    Rustdoc marks resolved type references as objects carrying both `id` and `path`.
    Stable across the format versions we have seen, but it is a heuristic."""
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
    """Source text cut from item spans."""

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
        """Rustdoc counts line and column from one, and the end column is exclusive.
        Without the column correction every excerpt loses its first character."""
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
        """None means local. Methods in impl blocks are absent from `paths` — only
        named paths land there — so an item in `index` without a path is local, not
        unknown. Without that rule most real code vanishes from the measurement."""
        entry = paths.get(item_id)
        if entry is None:
            return None if item_id in index else "?"
        crate_id = str(entry.get("crate_id", 0))
        return None if crate_id == "0" else externs.get(crate_id, "?")

    # The receiver type appears only as `Self` in the signature and must be taken from
    # the impl block.
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

    # What a body calls is invisible in rustdoc JSON — there are no bodies there. Names
    # are therefore matched against the source text, which is coarser than tsc's
    # resolution: two items sharing a name cannot be told apart. Overestimation is the
    # safer error, but the asymmetry against the TypeScript frontend is real and worth
    # knowing.
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
                continue  # generated or unreadable, not written code
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

    # External items only mentioned in `paths` — we cannot see their contracts, but we
    # must know they exist to decide whether they are free.
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

    # A trait item carries its methods as members; those methods are functions, and
    # their contract is the signature. A caller touching one method thus pays for that
    # method only.
    return Graph(name=crate_name(doc), items=items, **graph_args)
