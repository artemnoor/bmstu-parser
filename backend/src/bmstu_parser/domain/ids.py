from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Iterable
from typing import Any, TypeVar


def normalize_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def stable_id(kind: str, *parts: Any) -> str:
    """Return a deterministic opaque identifier for an ontology object."""

    natural_key = "|".join(normalize_key(part) for part in parts)
    digest = hashlib.sha1(f"{kind}|{natural_key}".encode()).hexdigest()[:20]
    return f"bmstu:{kind}:{digest}"


def legacy_stable_id(kind: str, *parts: Any) -> str:
    """Reproduce the pre-v2 identity algorithm for migration aliases."""

    return stable_id(kind, *parts)


T = TypeVar("T")


def deterministic_record_ids(
    kind: str,
    records: Iterable[T],
    *,
    key: Callable[[T], Iterable[Any]],
    legacy_key: Callable[[T, int], Iterable[Any]],
    legacy_indices: Iterable[int] | None = None,
) -> list[tuple[str, str]]:
    """Create reorder-stable IDs and the corresponding legacy aliases.

    The normal business key is used for the common case. If a source emits
    two records with the same key, a canonical payload signature becomes the
    first collision discriminator; only exact duplicate payloads use a
    deterministic ordinal. The source array position is never part of the
    new identity.
    """

    materialized = list(records)
    legacy_positions = (
        list(legacy_indices)
        if legacy_indices is not None
        else list(range(len(materialized)))
    )
    if len(legacy_positions) != len(materialized):
        raise ValueError("legacy_indices должен соответствовать records")
    entries: list[tuple[int, tuple[str, ...], str]] = []
    for index, record in enumerate(materialized):
        key_parts = tuple(normalize_key(part) for part in key(record))
        signature = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        entries.append((index, key_parts, signature))

    groups: dict[tuple[str, ...], list[tuple[int, str]]] = {}
    for index, key_parts, signature in entries:
        groups.setdefault(key_parts, []).append((index, signature))

    identifiers: list[str] = [""] * len(materialized)
    for key_parts, group in groups.items():
        if len(group) == 1:
            index, _ = group[0]
            identifiers[index] = stable_id(kind, *key_parts)
            continue
        by_signature: dict[str, list[int]] = {}
        for index, signature in group:
            by_signature.setdefault(signature, []).append(index)
        for signature, indexes in sorted(by_signature.items()):
            if len(indexes) == 1:
                identifiers[indexes[0]] = stable_id(
                    kind, *key_parts, "variant", signature
                )
            else:
                for ordinal, index in enumerate(sorted(indexes), start=1):
                    identifiers[index] = stable_id(
                        kind, *key_parts, "duplicate", ordinal
                    )

    legacy = [
        legacy_stable_id(kind, *legacy_key(record, legacy_position))
        for record, legacy_position in zip(materialized, legacy_positions, strict=True)
    ]
    return list(zip(identifiers, legacy, strict=True))


def link_id(link_type: str, from_id: str, to_id: str, *parts: Any) -> str:
    return stable_id("link", link_type, from_id, to_id, *parts)
