from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Iterable
from typing import Any, TypeVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str("" if value is None else value))
    return re.sub(r"\s+", " ", text).strip().casefold()


def canonical_source_key(value: Any) -> str:
    """Normalize URL source keys without changing non-URL business keys."""

    text = unicodedata.normalize("NFKC", str("" if value is None else value)).strip()
    parsed = urlsplit(text)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return normalize_key(text)

    hostname = parsed.hostname.casefold() if parsed.hostname else ""
    try:
        port = parsed.port
    except ValueError:
        return normalize_key(text)
    netloc = hostname
    if parsed.username or parsed.password:
        credentials = f"{parsed.username or ''}:{parsed.password or ''}@"
        netloc = credentials + netloc
    if port and not (
        (parsed.scheme.casefold() == "http" and port == 80)
        or (parsed.scheme.casefold() == "https" and port == 443)
    ):
        netloc = f"{netloc}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((parsed.scheme.casefold(), netloc, path, query, ""))


def _stable_part(value: Any) -> str:
    text = str("" if value is None else value)
    parsed = urlsplit(text.strip())
    if parsed.scheme.casefold() in {"http", "https"} and parsed.netloc:
        return canonical_source_key(text)
    return normalize_key(value)


def global_stable_id(university_id: str, entity_type: str, *parts: Any) -> str:
    """Build a reorder-stable ID scoped to one university and entity type."""

    university = normalize_key(university_id)
    kind = normalize_key(entity_type).replace(" ", "_")
    if not university or not kind:
        raise ValueError("university_id and entity_type are required")
    natural_key = "|".join(_stable_part(part) for part in parts)
    digest = hashlib.sha256(f"{university}|{kind}|{natural_key}".encode()).hexdigest()[
        :24
    ]
    return f"university:{university}:{kind}:{digest}"


T = TypeVar("T")


def deterministic_source_keys(
    records: Iterable[T], *, key: Callable[[T], Iterable[Any]]
) -> list[str]:
    """Return stable source keys for records sharing a source container.

    The primary key is made only from business fields.  A payload digest is
    used for genuine business-key variants and a duplicate ordinal is the
    final fallback for indistinguishable duplicate payloads.  In particular,
    the physical position of a normal record is never part of its key.
    """

    items = list(records)
    entries: list[tuple[int, tuple[str, ...], str]] = []
    for index, record in enumerate(items):
        business_key = tuple(_stable_part(value) for value in key(record))
        if not any(business_key):
            raise ValueError("A stable source key requires a non-empty business key")
        signature = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        entries.append((index, business_key, signature))

    groups: dict[tuple[str, ...], list[tuple[int, str]]] = {}
    for index, business_key, signature in entries:
        groups.setdefault(business_key, []).append((index, signature))

    result = [""] * len(items)
    for business_key, group in groups.items():
        base = "|".join(part for part in business_key if part)
        by_signature: dict[str, list[int]] = {}
        for index, signature in group:
            by_signature.setdefault(signature, []).append(index)
        if len(group) == 1:
            result[group[0][0]] = base
            continue
        for signature, indexes in sorted(by_signature.items()):
            if len(indexes) == 1:
                digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
                result[indexes[0]] = f"{base}|variant:{digest}"
                continue
            for ordinal, index in enumerate(sorted(indexes), start=1):
                result[index] = f"{base}|duplicate:{ordinal}"
    return result


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
        business_key = tuple(_stable_part(value) for value in key(record))
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
        else "|".join(_stable_part(value) for value in legacy_key(record, index))
        for index, record in enumerate(items)
    ]
    return list(zip(identifiers, aliases, strict=True))
