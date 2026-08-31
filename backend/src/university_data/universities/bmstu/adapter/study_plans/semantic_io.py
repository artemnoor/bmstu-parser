from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..outputs.writers import write_json
from .writers import write_csv, write_jsonl


def csv_semantic_rows(loads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "id",
        "discipline_id",
        "document_id",
        "table_id",
        "page_number",
        "row_index",
        "source_row_id",
        "code",
        "name",
        "semester",
        "weeks",
        "active",
        "has_numeric_load",
        "credits",
        "hours",
        "audited_hours",
        "independent_or_other_hours",
        "control",
        "control_tokens",
        "control_kinds",
        "raw",
        "raw_bands",
        "normalization_notes",
        "source_cell_ids",
        "source_word_ids",
    )
    output = []
    for load in loads:
        item = dict(load)
        item["control_tokens"] = json.dumps(
            item.get("control_tokens", []), ensure_ascii=False, separators=(",", ":")
        )
        item["control_kinds"] = json.dumps(
            item.get("control_kinds", []), ensure_ascii=False, separators=(",", ":")
        )
        item["raw"] = json.dumps(
            item.get("raw", {}), ensure_ascii=False, separators=(",", ":")
        )
        item["raw_bands"] = json.dumps(
            item.get("raw_bands", {}), ensure_ascii=False, separators=(",", ":")
        )
        item["normalization_notes"] = json.dumps(
            item.get("normalization_notes", []),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        item["source_cell_ids"] = json.dumps(
            item.get("source_cell_ids", []), ensure_ascii=False, separators=(",", ":")
        )
        item["source_word_ids"] = json.dumps(
            item.get("source_word_ids", []), ensure_ascii=False, separators=(",", ":")
        )
        output.append({field: item.get(field, "") for field in fields})
    return output


def write_semantic_dataset(data_dir: Path, semantic: dict[str, Any]) -> None:
    write_jsonl(
        data_dir / "study_plan_curriculum_rows.jsonl", semantic["curriculum_rows"]
    )
    write_jsonl(data_dir / "study_plan_disciplines.jsonl", semantic["disciplines"])
    write_jsonl(
        data_dir / "study_plan_discipline_entities.jsonl",
        semantic["resolution"]["entities"],
    )
    write_csv(
        data_dir / "study_plan_semester_load.csv",
        csv_semantic_rows(semantic["semester_loads"]),
        [
            "id",
            "discipline_id",
            "document_id",
            "table_id",
            "page_number",
            "row_index",
            "source_row_id",
            "code",
            "name",
            "semester",
            "weeks",
            "active",
            "has_numeric_load",
            "credits",
            "hours",
            "audited_hours",
            "independent_or_other_hours",
            "control",
            "control_tokens",
            "control_kinds",
            "raw",
            "raw_bands",
            "normalization_notes",
            "source_cell_ids",
            "source_word_ids",
        ],
    )
    write_json(
        data_dir / "study_plan_curriculum_schema.json",
        {"schema_version": "1.0", "documents": semantic["schemas"]},
    )
    write_json(data_dir / "study_plan_resolution_report.json", semantic["resolution"])
    write_json(data_dir / "study_plan_semantic_report.json", semantic["report"])
