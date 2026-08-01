"""Surprisal weighting of contracts.

CF counts size, but what actually costs comprehension is how *unexpected* a contract is.
`fn len(&self) -> usize` sits in the closure and costs tokens, but zero to grasp — you
knew what it did before reading it. A short but unpredictable contract costs more.

The measure: show a model only the name and ask it to write the contract. The more of the
real contract the guess hits, the less surprise, the lower the weight.

This is a measurement that did not exist before models did — it prices cost for exactly
the subject that will read the code.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

OLLAMA_URL = "http://localhost:11434/api/generate"

# Even a fully predictable contract costs something: you must at least see that it exists.
DEFAULT_FLOOR = 0.15

_WORD = re.compile(r"[A-Za-z_]\w*")


class Predictor(Protocol):
    def __call__(self, prompt: str) -> str: ...


def tokens_of(text: str) -> set[str]:
    return {word.lower() for word in _WORD.findall(text)}


def containment(actual: str, predicted: str) -> float:
    """How much of the real contract the guess anticipated.

    The direction is deliberate: we ask whether the model anticipated what is actually
    there, not whether it refrained from inventing extras. Guessing broadly is thus not
    punished, which is right — a reader who already considered more possibilities is not
    surprised.
    """
    real = tokens_of(actual)
    if not real:
        return 1.0
    return len(real & tokens_of(predicted)) / len(real)


def build_prompt(name: str, kind: str, crate: str) -> str:
    return (
        f"In the Rust crate `{crate}` there is a {kind} named `{name}`.\n"
        "Write the declaration you would expect it to have: the signature for a function, "
        "or the fields for a type. Guess from the name alone.\n"
        "Reply with Rust code only, no explanation, no markdown fence."
    )


def ollama(model: str, timeout: float = 120.0) -> Predictor:
    """Predictor against a locally running Ollama."""

    def predict(prompt: str) -> str:
        payload = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0},
            }
        ).encode()
        request = urllib.request.Request(
            OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read()).get("response", "")

    return predict


@dataclass
class Weighing:
    """Gives each contract a weight in [floor, 1] by how unexpected it is."""

    predictor: Predictor
    crate_name: str = "the crate"
    floor: float = DEFAULT_FLOOR
    cache_path: Path | None = None
    _cache: dict[str, float] = field(default_factory=dict, repr=False)
    failures: int = 0

    def __post_init__(self) -> None:
        if self.cache_path and self.cache_path.is_file():
            self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))

    def key(self, name: str, contract: str) -> str:
        digest = hashlib.sha256(f"{name}\0{contract}".encode()).hexdigest()
        return digest[:32]

    def weight(self, name: str, kind: str, contract: str) -> float:
        if not contract.strip():
            return 1.0
        key = self.key(name, contract)
        if key in self._cache:
            return self._cache[key]

        try:
            predicted = self.predictor(build_prompt(name, kind, self.crate_name))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            # With no guess there is no basis for a discount: full weight, and count
            # the failure so it shows in the report instead of fading in silently.
            self.failures += 1
            return 1.0

        surprise = 1.0 - containment(contract, predicted)
        value = self.floor + (1.0 - self.floor) * surprise
        self._cache[key] = value
        return value

    def save(self) -> None:
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(self._cache, indent=0), encoding="utf-8"
            )


def fixed(value: float) -> Callable[[str, str, str], float]:
    """Constant weight. Used by tests and as an explicit off switch."""

    def weigh(_name: str, _kind: str, _contract: str) -> float:
        return value

    return weigh
