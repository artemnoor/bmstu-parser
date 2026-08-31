from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..domain.ids import normalize_key, stable_id


def _resolution_key(discipline: dict[str, Any]) -> tuple[str, str]:
    code = normalize_key(discipline.get("code", ""))
    name = normalize_key(discipline.get("name", ""))
    if code and name:
        # In BMSTU PDFs numeric values are frequently local row numbers. A
        # code-only key would merge unrelated disciplines across plans.
        return "code_name", f"{code}|{name}"
    if name:
        return "name_department", "|".join(
            [name, normalize_key(discipline.get("department", ""))]
        )
    # Keep malformed source records isolated instead of merging all blanks.
    return "source", normalize_key(discipline.get("id", ""))


def _code_collision_candidates(
    disciplines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for discipline in disciplines:
        code = normalize_key(discipline.get("code", ""))
        if code:
            by_code[code].append(discipline)
    collisions = []
    for code, members in sorted(by_code.items()):
        names = sorted(
            {
                str(item.get("name", "")).strip()
                for item in members
                if str(item.get("name", "")).strip()
            }
        )
        if len(names) > 1:
            collisions.append(
                {
                    "code": code,
                    "candidate_names": names[:20],
                    "candidate_name_count": len(names),
                    "source_discipline_ids": [
                        str(item.get("id", "")) for item in members[:20]
                    ],
                }
            )
    return collisions


def resolve_disciplines(disciplines: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a non-destructive canonical index over repeated disciplines.

    This follows the McGill-style resolver idea but deliberately does not
    rewrite source discipline IDs. A code collision with different names is
    kept as a diagnostic candidate; it never merges unrelated source rows.
    """

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for discipline in disciplines:
        groups[_resolution_key(discipline)].append(discipline)
    code_collision_candidates = _code_collision_candidates(disciplines)

    entities: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda item: str(item.get("id", "")))
        names = sorted(
            {
                str(item.get("name", "")).strip()
                for item in members
                if str(item.get("name", "")).strip()
            }
        )
        codes = sorted(
            {
                str(item.get("code", "")).strip()
                for item in members
                if str(item.get("code", "")).strip()
            }
        )
        entity_id = stable_id("study-plan-discipline-entity", key[0], key[1])
        entity_conflicts: list[dict[str, Any]] = []
        if len(names) > 1:
            entity_conflicts.append({"kind": "name_conflict", "values": names})
        if len(codes) > 1:
            entity_conflicts.append({"kind": "code_conflict", "values": codes})
        status = "ambiguous" if entity_conflicts else "resolved"
        entities.append(
            {
                "id": entity_id,
                "resolution_key": {"kind": key[0], "value": key[1]},
                "status": status,
                "code": codes[0] if codes else "",
                "name": names[0] if names else "",
                "aliases": names,
                "source_discipline_ids": [str(item.get("id", "")) for item in members],
                "source_documents": sorted(
                    {str(item.get("document_id", "")) for item in members}
                ),
                "conflicts": entity_conflicts,
            }
        )
        for member in members:
            aliases.append(
                {
                    "source_discipline_id": member.get("id", ""),
                    "entity_id": entity_id,
                    "status": status,
                }
            )
        for conflict in entity_conflicts:
            conflicts.append({"entity_id": entity_id, **conflict})

    return {
        "schema_version": "1.0",
        "verification": {
            "all_source_disciplines_mapped": len(aliases) == len(disciplines),
            "no_ambiguous_entities": not conflicts,
            "code_collision_candidates_are_diagnostic": True,
            "passed": len(aliases) == len(disciplines),
        },
        "counts": {
            "source_disciplines": len(disciplines),
            "entities": len(entities),
            "aliases": len(aliases),
            "ambiguous_entities": sum(
                1 for entity in entities if entity["status"] == "ambiguous"
            ),
            "code_collision_candidates": len(code_collision_candidates),
        },
        "entities": entities,
        "aliases": aliases,
        "conflicts": conflicts,
        "code_collision_candidates": code_collision_candidates,
    }
