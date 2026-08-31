from __future__ import annotations

from collections import Counter
from typing import Any

from .resolution import resolve_disciplines
from .rules import validate_curriculum_contract
from .semantic_curriculum import SEMESTER_FIELD_NAMES, control_tokens
from .semantic_reconciliation import reconcile_totals
from .semantic_shared import clean


def evaluate_semantics(
    curriculum_tables: list[dict[str, Any]],
    processed_tables: set[str],
    schemas_by_document: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    disciplines: list[dict[str, Any]],
    loads: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    unresolved_tables = sorted(
        {table["id"] for table in curriculum_tables} - processed_tables
    )
    tables_without_schema = sorted(
        table["id"]
        for table in curriculum_tables
        if table.get("document_id", "") not in schemas_by_document
    )
    missing_subject_fields = [
        item["id"]
        for item in disciplines
        if not item.get("code") or not item.get("name")
    ]
    load_ids = [item["id"] for item in loads]
    reconciliation = reconcile_totals(disciplines, loads)
    numeric_control_leaks: list[dict[str, Any]] = []
    unclassified_controls: list[dict[str, Any]] = []
    active_without_numeric_or_control: list[dict[str, Any]] = []
    for load in loads:
        for field in SEMESTER_FIELD_NAMES[:-1]:
            tokens = control_tokens(load.get("raw", {}).get(field, ""))
            if tokens:
                numeric_control_leaks.append(
                    {
                        "load_id": load["id"],
                        "discipline_id": load["discipline_id"],
                        "semester": load["semester"],
                        "field": field,
                        "tokens": tokens,
                    }
                )
        control = clean(load.get("control", ""))
        if control and not load.get("control_tokens"):
            unclassified_controls.append(
                {
                    "load_id": load["id"],
                    "discipline_id": load["discipline_id"],
                    "semester": load["semester"],
                    "control": control,
                }
            )
        if load.get("active") and not load.get("has_numeric_load") and not control:
            active_without_numeric_or_control.append(
                {
                    "load_id": load["id"],
                    "discipline_id": load["discipline_id"],
                    "semester": load["semester"],
                    "raw": load.get("raw", {}),
                }
            )
    schema_warnings = [
        {
            "document_id": schema["document_id"],
            "source_table_id": schema["source_table_id"],
            "warnings": schema["warnings"],
        }
        for schema in schemas_by_document.values()
        if schema.get("warnings")
    ]
    source_gaps = {
        "disciplines_without_total_credits": sum(
            1 for item in disciplines if item.get("workload", {}).get("credits") is None
        ),
        "disciplines_without_audited_hours": sum(
            1
            for item in disciplines
            if item.get("workload", {}).get("audited_hours") is None
        ),
        "disciplines_without_department": sum(
            1 for item in disciplines if not item.get("department")
        ),
        "disciplines_with_unknown_part_type": sum(
            1 for item in disciplines if item.get("part_type") == "unknown"
        ),
        "unallocated_total_without_semester_rows": reconciliation[
            "unallocated_total_without_semester_rows"
        ],
    }
    discipline_ids = {discipline["id"] for discipline in disciplines}
    checks: dict[str, bool] = {
        "all_curriculum_tables_read": not unresolved_tables,
        "all_curriculum_documents_have_schema": not tables_without_schema,
        "discipline_ids_unique": len(discipline_ids) == len(disciplines),
        "discipline_subject_fields_present": not missing_subject_fields,
        "semester_loads_reference_disciplines": all(
            item["discipline_id"] in discipline_ids for item in loads
        ),
        "semester_load_ids_unique": len(load_ids) == len(set(load_ids)),
        "all_semantic_rows_reference_cells": all(
            bool(item.get("source_cell_ids")) for item in rows
        ),
        "allocated_semester_totals_reconcile": reconciliation[
            "active_semester_mismatches"
        ]
        == 0,
        "no_control_tokens_in_numeric_semester_fields": not numeric_control_leaks,
        "all_control_fields_classified": not unclassified_controls,
        "no_unexplained_active_semester_rows": not active_without_numeric_or_control,
        "no_schema_warnings": not schema_warnings,
    }
    curriculum_contract = validate_curriculum_contract(rows, disciplines, loads)
    checks.update(
        {
            f"curriculum_contract_{name}": passed
            for name, passed in curriculum_contract["verification"].items()
            if name != "passed"
        }
    )
    resolution = resolve_disciplines(disciplines)
    checks["passed"] = all(checks.values())
    report = {
        "schema_version": "1.1",
        "verification": checks,
        "counts": {
            "curriculum_tables": len(curriculum_tables),
            "processed_curriculum_tables": len(processed_tables),
            "curriculum_rows": len(rows),
            "disciplines": len(disciplines),
            "semester_loads": len(loads),
            "active_semester_loads": sum(1 for item in loads if item["active"]),
            "numeric_semester_loads": sum(
                1 for item in loads if item["has_numeric_load"]
            ),
            "controls": sum(1 for item in loads if item["control"]),
        },
        "reconciliation": reconciliation,
        "schemas": {
            "documents": len(schemas_by_document),
            "semester_counts": dict(
                Counter(
                    schema["semester_count"] for schema in schemas_by_document.values()
                )
            ),
        },
        "missing_subject_fields": missing_subject_fields,
        "unresolved_tables": unresolved_tables,
        "tables_without_schema": tables_without_schema,
        "source_gaps": source_gaps,
        "anomalies": {
            "control_in_numeric_semester_fields": {
                "count": len(numeric_control_leaks),
                "examples": numeric_control_leaks[:20],
            },
            "unclassified_controls": {
                "count": len(unclassified_controls),
                "examples": unclassified_controls[:20],
            },
            "active_without_numeric_or_control": {
                "count": len(active_without_numeric_or_control),
                "examples": active_without_numeric_or_control[:20],
            },
            "schema_warnings": {
                "count": len(schema_warnings),
                "examples": schema_warnings[:20],
            },
        },
        "curriculum_contract": curriculum_contract,
        "resolution": {
            "counts": resolution["counts"],
            "verification": resolution["verification"],
            "conflicts": resolution["conflicts"],
            "code_collision_candidates": resolution["code_collision_candidates"],
        },
        "warnings": schema_warnings,
    }
    return report, resolution
