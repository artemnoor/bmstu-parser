from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any


def normalize_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def stable_id(kind: str, *parts: Any) -> str:
    """Return a deterministic opaque identifier for an ontology object."""

    natural_key = "|".join(normalize_key(part) for part in parts)
    digest = hashlib.sha1(f"{kind}|{natural_key}".encode("utf-8")).hexdigest()[:20]
    return f"bmstu:{kind}:{digest}"


def link_id(link_type: str, from_id: str, to_id: str, *parts: Any) -> str:
    return stable_id("link", link_type, from_id, to_id, *parts)

