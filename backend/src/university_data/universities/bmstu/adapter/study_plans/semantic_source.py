from __future__ import annotations

import csv
import json
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .....core.source_models import SourceCurriculum
from .....domain.provenance import SourceProvenance
from .readers import DocumentReader, get_reader_backend
from .semantics import extract_semantics


def _write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
            + "\n"
            for value in values
        ),
        encoding="utf-8",
    )


def _write_reader_result(
    data_dir: Path,
    document_id: str,
    pages: list[dict[str, Any]],
    tables: list[dict[str, Any]],
) -> None:
    _write_jsonl(
        data_dir / "study_plan_pages.jsonl",
        [page | {"document_id": document_id} for page in pages],
    )
    _write_jsonl(
        data_dir / "study_plan_tables.jsonl",
        [
            {
                key: table.get(key)
                for key in (
                    "id",
                    "document_id",
                    "page_number",
                    "table_index",
                    "section",
                    "bbox",
                    "row_count",
                    "column_count",
                    "extraction_method",
                )
            }
            for table in tables
        ],
    )
    cell_path = data_dir / "study_plan_cells.csv"
    fields = [
        "id",
        "table_id",
        "document_id",
        "page_number",
        "section",
        "row_index",
        "column_index",
        "text",
        "bbox",
        "word_ids",
        "cell_kind",
    ]
    with cell_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for table in tables:
            for row in table.get("rows", []):
                for cell in row:
                    writer.writerow(
                        {
                            "id": cell.get("id", ""),
                            "table_id": cell.get("table_id", table.get("id", "")),
                            "document_id": document_id,
                            "page_number": table.get("page_number"),
                            "section": table.get("section", ""),
                            "row_index": cell.get("row_index", 0),
                            "column_index": cell.get("column_index", 0),
                            "text": cell.get("text", ""),
                            "bbox": json.dumps(
                                cell.get("bbox"),
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                            "word_ids": json.dumps(
                                cell.get("word_ids", []),
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                            "cell_kind": cell.get("cell_kind", ""),
                        }
                    )


def source_rows_from_semantic(semantic: dict[str, Any]) -> list[dict[str, Any]]:
    loads_by_discipline: dict[str, list[dict[str, Any]]] = {}
    for load in semantic.get("semester_loads", []):
        if isinstance(load, dict) and load.get("discipline_id"):
            loads_by_discipline.setdefault(load["discipline_id"], []).append(load)

    rows: list[dict[str, Any]] = []
    for discipline in semantic.get("disciplines", []):
        if not isinstance(discipline, dict):
            continue
        workload = discipline.get("workload", {})
        class_hours = discipline.get("class_hours", {})
        discipline_loads = loads_by_discipline.get(discipline.get("id", ""), [])
        rows.append(
            {
                "code": discipline.get("code", ""),
                "discipline": discipline.get("name", ""),
                "department": discipline.get("department", ""),
                "total_hours": workload.get("hours"),
                "credits": workload.get("credits"),
                "components": {
                    key: value
                    for key, value in {
                        "lecture": class_hours.get("lecture"),
                        "seminar": class_hours.get("seminar"),
                        "lab": class_hours.get("lab"),
                        "independent_or_other": class_hours.get("independent_or_other"),
                    }.items()
                    if value is not None
                },
                "semester": (
                    discipline_loads[0].get("semester") if discipline_loads else None
                ),
                "semester_loads": [
                    {
                        key: load.get(key)
                        for key in (
                            "semester",
                            "weeks",
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
                    }
                    | {
                        "extensions": {
                            "semantic_source_id": load.get("id", ""),
                            "source_row_id": load.get("source_row_id", ""),
                        }
                    }
                    for load in discipline_loads
                ],
                "extensions": {
                    "semantic_source_id": discipline.get("id", ""),
                    "source_row_id": discipline.get("source_row_id", ""),
                    "part_type": discipline.get("part_type", ""),
                    "section_path": discipline.get("section_path", []),
                    "source_cell_ids": discipline.get("source_cell_ids", []),
                    "semantic_row": discipline,
                },
                "raw": discipline,
            }
        )
    return rows


# Kept private for the adapter's older internal callers while exposing a
# descriptive name for the generic Source DTO bridge.
_source_rows = source_rows_from_semantic


def parse_source_curriculum(
    path: Path,
    *,
    document_id: str,
    program_key: str,
    name: str,
    provenance: SourceProvenance,
    reader_backend: str | DocumentReader = "native",
) -> SourceCurriculum:
    """Parse one PDF/DOCX into a typed curriculum source DTO.

    The adapter owns BMSTU's geometry and semantic rules, but it returns only
    a ``SourceCurriculum``.  The platform pipeline subsequently performs the
    canonical normalization and ontology projection.
    """

    reader = get_reader_backend(reader_backend)
    pages, tables, layout_text, warnings = reader.extract(path, document_id)
    with tempfile.TemporaryDirectory(prefix="university_data_semantic_") as raw:
        data_dir = Path(raw)
        _write_reader_result(data_dir, document_id, pages, tables)
        semantic = extract_semantics(data_dir)
    report = dict(semantic.get("report", {}))
    if warnings:
        report = {**report, "reader_warnings": warnings}
    return SourceCurriculum(
        source_key=f"{program_key}:curriculum",
        name=name,
        program_key=program_key,
        path=path,
        rows=tuple(source_rows_from_semantic(semantic)),
        raw={
            "document_id": document_id,
            "layout_text": layout_text,
            "semantic_report": report,
            "semantic_schema_count": len(semantic.get("schemas", [])),
            "semantic_row_count": len(semantic.get("curriculum_rows", [])),
        },
        provenance=provenance,
        extensions={
            "semantic_report": report,
            "semantic_document_id": document_id,
            "semantic_warnings": warnings,
        },
    )


__all__ = ["parse_source_curriculum", "source_rows_from_semantic"]
