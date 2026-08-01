"""Överraskningsviktning av kontrakt.

CF räknar storlek, men det som faktiskt kostar att förstå är hur *oväntat* ett kontrakt är.
`fn len(&self) -> usize` ligger i slutningen och kostar tokens, men noll att begripa — du
visste vad det gjorde innan du läste det. Ett kort men oförutsägbart kontrakt kostar mer.

Måttet på det: visa en modell bara namnet och be den skriva kontraktet. Ju mer av det
verkliga kontraktet gissningen träffar, desto mindre överraskning, desto lägre vikt.

Det är en mätning som inte fanns innan modeller fanns — den mäter kostnaden hos exakt det
subjekt som ska läsa koden.
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

# Även ett helt förutsägbart kontrakt kostar något: du måste åtminstone se att det finns.
DEFAULT_FLOOR = 0.15

_WORD = re.compile(r"[A-Za-z_]\w*")


class Predictor(Protocol):
    def __call__(self, prompt: str) -> str: ...


def tokens_of(text: str) -> set[str]:
    return {word.lower() for word in _WORD.findall(text)}


def containment(actual: str, predicted: str) -> float:
    """Hur stor del av det verkliga kontraktet gissningen förutsåg.

    Riktningen är avsiktlig: vi frågar om modellen förutsåg det som faktiskt står där, inte
    om den lät bli att hitta på extra. Att gissa brett bestraffas alltså inte, vilket är
    rätt — en läsare som redan övervägt fler möjligheter blir inte överraskad.
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
    """Predictor mot en lokalt körande Ollama."""

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
    """Ger varje kontrakt en vikt i [floor, 1] efter hur oväntat det är."""

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
            # Utan gissning finns ingen grund att rabattera: full vikt, och räkna
            # misslyckandet så att det syns i rapporten i stället för att tyst blekna in.
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
    """Konstant vikt. Används av tester och som uttrycklig av-knapp."""

    def weigh(_name: str, _kind: str, _contract: str) -> float:
        return value

    return weigh
