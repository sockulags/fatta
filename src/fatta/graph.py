"""Language-neutral core: a graph of items, and the computations over it.

Everything language-specific lives in a frontend that builds this graph — `rustdoc` for
Rust, `typescript` for TS. The computations below know nothing about any language; they
can only follow contracts and decide when they are allowed to stop following.

Three kinds of item suffice: `function` (including methods), `type` (struct, enum, class,
interface, alias) and `member` (field, variant, property).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

FUNCTION = "function"
TYPE = "type"
MEMBER = "member"

# Packages whose contracts the reader already knows. They cost zero, and they terminate
# the walk: if you know the type, you do not need its insides either.
WELLKNOWN = frozenset(
    {
        # Rust
        "std", "core", "alloc", "proc_macro", "serde", "tokio", "anyhow", "thiserror",
        # TypeScript and JS
        "typescript", "lib", "node", "@types/node", "react", "@types/react",
        "react-dom", "@types/react-dom", "next", "zod",
    }
)

_WORD = re.compile(r"[A-Za-z_]\w*")
_ACCESS = re.compile(r"\.\s*([A-Za-z_$]\w*)")
_BINDING = re.compile(r"\b([A-Za-z_$]\w*)\s*:")
_PATH_SEGMENT = re.compile(r"(?:::|\.)\s*([A-Za-z_$]\w*)")


def estimate_tokens(text: str) -> int:
    """Rough character-based estimate.

    Good enough for ranking. Swap in a real tokenizer before publishing absolute
    thresholds."""
    return max(1, round(len(text) / 3.6)) if text else 0


def used_names(body: str) -> set[str]:
    """Which members a body actually mentions.

    Neither rustdoc nor tsc provides bodies in structured form, so this is read from the
    source text. The heuristic is deliberately generous — including too much overestimates
    the cost, and overestimation is the safer error."""
    return (
        set(_ACCESS.findall(body))
        | set(_BINDING.findall(body))
        | set(_PATH_SEGMENT.findall(body))
    )


@dataclass(frozen=True)
class Item:
    """A named thing in a codebase."""

    id: str
    name: str
    kind: str
    contract: str
    """The declaration: signature for a function, header for a type."""
    body: str = ""
    """The implementation. Only functions have one, and it is only counted for the
    function being measured — never for its dependencies."""
    members: tuple[str, ...] = ()
    refs: tuple[str, ...] = ()
    """Item ids the contract touches."""
    owner: tuple[str, ...] = ()
    """The receiver type of a method. It is rarely in the signature and must be carried
    separately."""
    calls: tuple[str, ...] = ()
    """What the body calls or constructs.

    In Rust the signature carries the dependencies. In TypeScript, and especially in
    React, it does not — a component takes no parameters and creates everything
    internally. Without these edges, such code appears to have no dependencies at all,
    which is the most dangerous possible failure: the set is presented as closed when it
    is not."""
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
    """Items plus the computations that turn them into a footprint."""

    name: str
    items: dict[str, Item]
    use_directed: bool = True
    wellknown: frozenset[str] = WELLKNOWN
    count_tokens: Callable[[str], int] = estimate_tokens
    weigh: Callable[[str, str, str], float] | None = None
    _closure_cache: dict[tuple[str, frozenset[str] | None], frozenset[str]] = field(
        default_factory=dict, repr=False
    )

    # -- lookup -----------------------------------------------------------------

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

    # -- contracts --------------------------------------------------------------

    def members_of(self, item_id: str, used: set[str] | None) -> list[str]:
        """Members of a type, filtered to what the code actually touches."""
        item = self.items.get(item_id)
        if item is None or item.kind != TYPE:
            return []
        if used is None:
            return list(item.members)
        return [m for m in item.members if self.name_of(m) in used]

    def contract_text(self, item_id: str, used: set[str] | None = None) -> str:
        """What a reader must see of a dependency — never its implementation.

        Types are projected down to their header plus the members that are mentioned. A
        wide struct of which you touch three fields costs three fields, not three
        hundred."""
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

    # -- the closure ------------------------------------------------------------

    def surface(
        self, item_id: str, used: set[str] | None = None, include_calls: bool = False
    ) -> set[str]:
        """What an item's contract touches.

        The signature is never filtered — the reader must see those types regardless. It
        is the types' *insides* that get pruned to what is used.

        `include_calls` applies only to the function being measured. You must know the
        contract of what you call yourself, but not of what *they* call — their contracts
        suffice. That rule is what keeps the closure finite instead of swelling to the
        whole program."""
        item = self.items.get(item_id)
        if item is None:
            return set()
        if item.kind == TYPE:
            # A type's own refs are inheritance, implements, and whatever an alias points
            # to — those belong to the type itself and are not pruned by usage.
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
        """Transitive contract closure. Well-known items terminate the walk."""
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

    # -- pruning value ----------------------------------------------------------

    def pruning_value(self, item_id: str) -> int:
        """How much closure hangs below an item.

        This is what a trustworthy contract at this spot would save a reader — i.e. where
        documenting pays off. A doc deep down the tree saves almost nothing, because you
        had to walk there to read it."""
        below = self.closure(item_id)
        return sum(
            self.count_tokens(self.contract_text(dep))
            for dep in below
            if not self.is_free(dep)
        )
