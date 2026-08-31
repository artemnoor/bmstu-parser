from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Iterable
from typing import Any


def normalize_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def stable_id(kind: str, *parts: Any) -> str:
    natural_key = "|".join(normalize_key(part) for part in parts)
    digest = hashlib.sha1(f"{kind}|{natural_key}".encode()).hexdigest()[:20]
    return f"bmstu:{kind}:{digest}"


def link_id(link_type: str, from_id: str, to_id: str, *parts: Any) -> str:
    return stable_id("link", link_type, from_id, to_id, *parts)


def deterministic_record_ids(
    kind: str,
    records: Iterable[Any],
    *,
    key: Callable[[Any], Iterable[Any]],
    legacy_key: Callable[[Any, int], Iterable[Any]],
    legacy_indices: Iterable[int] | None = None,
) -> list[tuple[str, str]]:
    materialized = list(records)
    positions = list(legacy_indices or range(len(materialized)))
    if len(positions) != len(materialized):
        raise ValueError("legacy_indices must match records")
    entries = []
    for index, record in enumerate(materialized):
        parts = tuple(normalize_key(part) for part in key(record))
        signature = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        entries.append((index, parts, signature))
    groups: dict[tuple[str, ...], list[tuple[int, str]]] = {}
    for index, parts, signature in entries:
        groups.setdefault(parts, []).append((index, signature))
    identifiers = [""] * len(materialized)
    for parts, group in groups.items():
        if len(group) == 1:
            identifiers[group[0][0]] = stable_id(kind, *parts)
            continue
        by_signature: dict[str, list[int]] = {}
        for index, signature in group:
            by_signature.setdefault(signature, []).append(index)
        for signature, indexes in sorted(by_signature.items()):
            if len(indexes) == 1:
                identifiers[indexes[0]] = stable_id(kind, *parts, "variant", signature)
            else:
                for ordinal, index in enumerate(sorted(indexes), start=1):
                    identifiers[index] = stable_id(kind, *parts, "duplicate", ordinal)
    return [
        (identifier, stable_id(kind, *legacy_key(record, position)))
        for identifier, record, position in zip(
            identifiers, materialized, positions, strict=True
        )
    ]
