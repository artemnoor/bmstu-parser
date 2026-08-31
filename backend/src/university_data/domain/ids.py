from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Iterable
from typing import Any, TypeVar


def normalize_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def global_stable_id(university_id: str, entity_type: str, *parts: Any) -> str:
    """Build a reorder-stable ID scoped to one university and entity type."""

    university = normalize_key(university_id)
    kind = normalize_key(entity_type).replace(" ", "_")
    if not university or not kind:
        raise ValueError("university_id and entity_type are required")
    natural_key = "|".join(normalize_key(part) for part in parts)
    digest = hashlib.sha256(f"{university}|{kind}|{natural_key}".encode()).hexdigest()[
        :24
    ]
    return f"university:{university}:{kind}:{digest}"


T = TypeVar("T")


def deterministic_record_ids(
    university_id: str,
    entity_type: str,
    records: Iterable[T],
    *,
    key: Callable[[T], Iterable[Any]],
    legacy_key: Callable[[T, int], Iterable[Any]] | None = None,
) -> list[tuple[str, str | None]]:
    """Return reorder-stable IDs and optional legacy aliases.

    Exact business-key collisions are disambiguated by a sorted payload
    signature; only exact duplicate payloads need a deterministic ordinal.
    """

    items = list(records)
    entries = []
    for index, record in enumerate(items):
        business_key = tuple(normalize_key(value) for value in key(record))
        signature = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
        entries.append((index, business_key, signature))
    groups: dict[tuple[str, ...], list[tuple[int, str]]] = {}
    for index, business_key, signature in entries:
        groups.setdefault(business_key, []).append((index, signature))
    identifiers = [""] * len(items)
    for business_key, group in groups.items():
        by_signature: dict[str, list[int]] = {}
        for index, signature in group:
            by_signature.setdefault(signature, []).append(index)
        for signature, indexes in sorted(by_signature.items()):
            if len(indexes) == 1:
                suffix: tuple[Any, ...] = (
                    () if len(group) == 1 else ("variant", signature)
                )
                identifiers[indexes[0]] = global_stable_id(
                    university_id, entity_type, *business_key, *suffix
                )
            else:
                for ordinal, index in enumerate(sorted(indexes), start=1):
                    identifiers[index] = global_stable_id(
                        university_id, entity_type, *business_key, "duplicate", ordinal
                    )
    aliases = [
        None
        if legacy_key is None
        else "|".join(normalize_key(value) for value in legacy_key(record, index))
        for index, record in enumerate(items)
    ]
    return list(zip(identifiers, aliases, strict=True))
