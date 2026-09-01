from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .ids import canonical_source_key

_ENTITY_TYPES = {
    "universities": "university",
    "faculties": "faculty",
    "departments": "department",
    "study_directions": "study_direction",
    "programs": "program",
    "curricula": "curriculum",
    "teachers": "teacher",
    "admission_requirements": "admission_requirement",
    "tuition_options": "tuition_option",
    "disciplines": "discipline",
    "semesters": "semester",
    "semester_loads": "semester_load",
}


def _source_key(record: dict[str, Any]) -> str:
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        return ""
    source_key = str(provenance.get("source_key", "")).strip()
    if source_key:
        return canonical_source_key(source_key)
    sources = provenance.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if isinstance(source, dict) and str(source.get("source_key", "")).strip():
                return canonical_source_key(source["source_key"])
    return ""


def _explicit_aliases(record: dict[str, Any]) -> Iterable[str]:
    extensions = record.get("extensions")
    if not isinstance(extensions, dict):
        return ()
    result: list[str] = []
    for values in extensions.values():
        if not isinstance(values, dict):
            continue
        aliases = values.get("legacy_ids")
        if isinstance(aliases, str):
            aliases = [aliases]
        if isinstance(aliases, list):
            result.extend(str(alias).strip() for alias in aliases if str(alias).strip())
    return result


def build_id_aliases(
    previous: dict[str, list[dict[str, Any]]],
    current: dict[str, list[dict[str, Any]]],
    *,
    existing: Iterable[dict[str, Any]] = (),
) -> list[dict[str, str]]:
    """Build generic aliases from explicit legacy IDs and source identity.

    A provider can publish legacy IDs through ``SourceRecord.legacy_ids``.
    When a source key remains the same but an ID policy changes, the previous
    canonical ID is also retained as an alias automatically.
    """

    aliases: dict[tuple[str, str], str] = {}
    for item in existing:
        if not isinstance(item, dict):
            continue
        legacy = str(item.get("legacy_id", "")).strip()
        canonical = str(item.get("canonical_id", "")).strip()
        entity_type = str(item.get("entity_type", "")).strip()
        if legacy and canonical and legacy != canonical:
            aliases[(entity_type, legacy)] = canonical

    previous_by_identity: dict[tuple[str, str], str] = {}
    for dataset, records in previous.items():
        for record in records:
            identifier = str(record.get("id", "")).strip()
            source_key = _source_key(record)
            if identifier and source_key:
                previous_by_identity[(dataset, source_key)] = identifier

    for dataset, records in current.items():
        entity_type = _ENTITY_TYPES.get(dataset, dataset)
        for record in records:
            canonical = str(record.get("id", "")).strip()
            if not canonical:
                continue
            for legacy in _explicit_aliases(record):
                if legacy != canonical:
                    alias_key = (entity_type, legacy)
                    previous_alias = aliases.get(alias_key)
                    if previous_alias and previous_alias != canonical:
                        raise ValueError(
                            f"Conflicting ID alias for {entity_type!r}: {legacy!r}"
                        )
                    aliases[alias_key] = canonical
            source_key = _source_key(record)
            previous_id = (
                previous_by_identity.get((dataset, source_key)) if source_key else None
            )
            if previous_id and previous_id != canonical:
                alias_key = (entity_type, previous_id)
                previous_alias = aliases.get(alias_key)
                if previous_alias and previous_alias != canonical:
                    raise ValueError(
                        f"Conflicting ID alias for {entity_type!r}: {previous_id!r}"
                    )
                aliases[alias_key] = canonical

    return [
        {
            "legacy_id": legacy,
            "canonical_id": canonical,
            "entity_type": entity_type,
        }
        for (entity_type, legacy), canonical in sorted(aliases.items())
    ]


__all__ = ["build_id_aliases"]
