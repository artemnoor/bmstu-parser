from __future__ import annotations

from collections import Counter
from typing import Any


def validate_curriculum_contract(
    rows: list[dict[str, Any]],
    disciplines: list[dict[str, Any]],
    semester_loads: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run the portable, typed curriculum lint inspired by SPbU/UTD.

    The validator reports facts and never repairs records. This is the seam
    where future source-specific rules can be added without changing the
    reader or the ontology writer.
    """

    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    discipline_ids = [str(item.get("id", "")) for item in disciplines]
    duplicate_discipline_ids = [
        key for key, count in Counter(discipline_ids).items() if key and count > 1
    ]
    for identifier in duplicate_discipline_ids:
        violations.append({"rule": "unique_discipline_ids", "id": identifier})

    missing_subject_fields = [
        str(item.get("id", ""))
        for item in disciplines
        if not str(item.get("code", "")).strip()
        or not str(item.get("name", "")).strip()
    ]
    for identifier in missing_subject_fields:
        violations.append({"rule": "discipline_code_and_name", "id": identifier})

    known_ids = set(discipline_ids)
    orphan_loads = [
        str(item.get("id", ""))
        for item in semester_loads
        if str(item.get("discipline_id", "")) not in known_ids
    ]
    for identifier in orphan_loads:
        violations.append({"rule": "load_references_discipline", "id": identifier})

    load_ids = [str(item.get("id", "")) for item in semester_loads]
    duplicate_load_ids = [
        key for key, count in Counter(load_ids).items() if key and count > 1
    ]
    for identifier in duplicate_load_ids:
        violations.append({"rule": "unique_semester_load_ids", "id": identifier})

    rows_without_sources = [
        str(item.get("id", "")) for item in rows if not item.get("source_cell_ids")
    ]
    for identifier in rows_without_sources:
        violations.append({"rule": "semantic_row_has_source_cells", "id": identifier})

    unknown_part_type = [
        str(item.get("id", ""))
        for item in disciplines
        if item.get("part_type") == "unknown"
    ]
    for identifier in unknown_part_type:
        warnings.append({"rule": "known_part_type", "id": identifier})

    return {
        "verification": {
            "unique_discipline_ids": not duplicate_discipline_ids,
            "discipline_code_and_name_present": not missing_subject_fields,
            "semester_loads_reference_disciplines": not orphan_loads,
            "unique_semester_load_ids": not duplicate_load_ids,
            "semantic_rows_have_source_cells": not rows_without_sources,
            "passed": not violations,
        },
        "violations": violations,
        "warnings": warnings,
        "counts": {
            "rows": len(rows),
            "disciplines": len(disciplines),
            "semester_loads": len(semester_loads),
            "violations": len(violations),
            "warnings": len(warnings),
        },
    }
