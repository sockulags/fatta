"""Finds the source tree that a rustdoc JSON's spans point into.

Spans are relative to the crate root, so for dependencies fetched from crates.io the root
must be looked up in the registry's source cache.
"""

from __future__ import annotations

import os
from pathlib import Path


def cargo_home() -> Path:
    return Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo")


def crate_name(doc: dict) -> str:
    root = doc["index"].get(str(doc["root"])) or {}
    return root.get("name") or "?"


def looks_like_crate_root(path: Path) -> bool:
    return (path / "Cargo.toml").is_file() or (path / "src").is_dir()


def locate(doc: dict, doc_path: Path, override: Path | None = None) -> Path:
    """Best guess at the crate root.

    Order: explicit flag, the target/doc convention three levels up, and finally the
    registry source cache by name and version.
    """
    if override is not None:
        return override

    conventional = doc_path.parent.parent.parent
    if looks_like_crate_root(conventional):
        return conventional

    name, version = crate_name(doc), doc.get("crate_version")
    if name != "?" and version:
        registry = cargo_home() / "registry" / "src"
        for index_dir in sorted(registry.glob("*")):
            candidate = index_dir / f"{name}-{version}"
            if looks_like_crate_root(candidate):
                return candidate

    return conventional
