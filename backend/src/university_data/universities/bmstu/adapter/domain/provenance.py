from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SOURCE_FIELDS = (
    "source_page",
    "list_api",
    "detail_api",
    "detail_page",
    "fetched_at_utc",
    "raw_snapshot_path",
    "source_key",
)


def _merge_lists(left: list[Any], right: list[Any]) -> list[Any]:
    """Append list values by equality without requiring hashable items."""

    merged = list(left)
    for item in right:
        if item not in merged:
            merged.append(item)
    return merged


def _observation(value: Mapping[str, Any]) -> dict[str, Any]:
    return dict(value)


def _observations(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = value.get("sources")
    candidates = raw if isinstance(raw, list) else []
    if not candidates:
        candidates = [value]
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        item = _observation(candidate)
        if (
            any(item.get(field) for field in SOURCE_FIELDS)
            or any(
                key not in {"sources", *SOURCE_FIELDS}
                and value not in (None, "", [], {})
                for key, value in item.items()
            )
        ) and item not in result:
            result.append(item)
    return result


def provenance_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        result = value.to_dict()
        if isinstance(result, dict):
            return result
    if isinstance(value, Mapping):
        result = dict(value)
        if "sources" not in result:
            observations = _observations(result)
            if observations:
                result["sources"] = observations
        return result
    return {field: "" for field in SOURCE_FIELDS}


def merge_provenance(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge observations while keeping the old scalar provenance contract."""

    merged: dict[str, Any] = dict(left)
    for field_name, value in right.items():
        if field_name == "sources" or value in (None, "", [], {}):
            continue
        if field_name not in merged or merged[field_name] in (None, "", [], {}):
            merged[field_name] = value
        elif isinstance(value, list) and isinstance(merged[field_name], list):
            merged[field_name] = _merge_lists(merged[field_name], value)
    for field in SOURCE_FIELDS:
        merged[field] = str(left.get(field) or right.get(field) or "")

    observations = _observations(left)
    for item in _observations(right):
        if item not in observations:
            observations.append(item)
    if observations:
        merged["sources"] = observations
    return merged
