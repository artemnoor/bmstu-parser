from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..outputs.writers import write_json
from ..runtime.lineage import PipelineRun
from .semantic_curriculum import (
    control_kinds as _control_kinds,
    control_tokens as _control_tokens,
    number as _number,
    number_tokens as _number_tokens,
    part_type as _part_type,
    row_kind as _row_kind,
    semantic_row as _semantic_row,
    strip_control_tokens as _strip_control_tokens,
    unique_tokens as _unique_tokens,
)
from .semantic_geometry import band_payload as _band_payload
from .semantic_geometry import bbox as _bbox
from .semantic_geometry import cell_from_csv as _cell_from_csv
from .semantic_geometry import control_assignments as _control_assignments
from .semantic_geometry import find_header_span as _find_header_span
from .semantic_geometry import join_words as _join_words
from .semantic_geometry import normalized_span as _normalized_span
from .semantic_geometry import overlap as _overlap
from .semantic_geometry import page_words_by_key as _page_words_by_key
from .semantic_geometry import row_words as _row_words
from .semantic_geometry import semester_spans as _semester_spans
from .semantic_geometry import table_bounds as _table_bounds
from .semantic_io import csv_semantic_rows as _csv_semantic_rows
from .semantic_io import write_semantic_dataset
from .semantic_ontology import extend_ontology_with_semantics
from .semantic_quality import evaluate_semantics
from .semantic_reconciliation import reconcile_totals as _reconcile_totals
from .semantic_schema import (
    BASE_FIELD_NAMES,
    SEMESTER_FIELD_NAMES,
    discover_schemas as _discover_schemas,
    iter_curriculum_table_rows as _iter_curriculum_table_rows,
)
from .semantic_shared import clean as _clean
from .semantic_shared import json_value as _json_value
from .semantic_shared import read_jsonl as _read_jsonl


def extract_semantics(data_dir: Path) -> dict[str, Any]:
    """Build semantic curriculum projections from canonical PDF cells."""

    tables = _read_jsonl(data_dir / "study_plan_tables.jsonl")
    table_by_id = {table["id"]: table for table in tables}
    curriculum_tables = [
        table for table in tables if table.get("section") == "curriculum"
    ]
    cells_path = data_dir / "study_plan_cells.csv"
    schemas_by_document = _discover_schemas(tables, cells_path)
    page_words = _page_words_by_key(data_dir)
    curriculum_ids = {table["id"] for table in curriculum_tables}
    rows: list[dict[str, Any]] = []
    disciplines: list[dict[str, Any]] = []
    loads: list[dict[str, Any]] = []
    processed_tables: set[str] = set()
    state_by_document: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"section_path": [], "part_type": "unknown"}
    )
    for table_identifier, table_rows in _iter_curriculum_table_rows(
        cells_path, curriculum_ids
    ):
        table = table_by_id[table_identifier]
        processed_tables.add(table_identifier)
        schema = schemas_by_document.get(table.get("document_id", ""))
        words = page_words.get(
            (table.get("document_id", ""), int(table.get("page_number") or 0)), {}
        )
        state = state_by_document[table.get("document_id", "")]
        for row_index in sorted(table_rows):
            row_record, discipline, row_loads = _semantic_row(
                table,
                row_index,
                table_rows[row_index],
                schema,
                words,
                state,
            )
            rows.append(row_record)
            if discipline is not None:
                disciplines.append(discipline)
                loads.extend(row_loads)

    report, resolution = evaluate_semantics(
        curriculum_tables,
        processed_tables,
        schemas_by_document,
        rows,
        disciplines,
        loads,
    )
    return {
        "schemas": list(schemas_by_document.values()),
        "curriculum_rows": rows,
        "disciplines": disciplines,
        "semester_loads": loads,
        "resolution": resolution,
        "report": report,
    }


def enrich_existing_dataset(result_dir: Path) -> dict[str, Any]:
    data_dir = result_dir / "study_plan_data"
    if not (data_dir / "study_plan_cells.csv").exists():
        raise FileNotFoundError(
            f"Не найден полный набор ячеек: {data_dir / 'study_plan_cells.csv'}"
        )
    run = PipelineRun(result_dir, "extract_study_plan_semantics")
    try:
        semantic = extract_semantics(data_dir)
        write_semantic_dataset(data_dir, semantic)
        ontology = extend_ontology_with_semantics(data_dir, semantic)
        main_report = result_dir / "parse_report.json"
        if main_report.exists():
            report = json.loads(main_report.read_text(encoding="utf-8"))
            report["study_plan_semantics"] = semantic["report"]
            write_json(main_report, report)
        run.stage(
            "semantic_transform",
            inputs=[
                "study_plan_data/study_plan_tables.jsonl",
                "study_plan_data/study_plan_rows.jsonl",
                "study_plan_data/study_plan_cells.csv",
                "study_plan_data/study_plan_pages.jsonl",
            ],
            outputs=[
                "study_plan_data/study_plan_curriculum_rows.jsonl",
                "study_plan_data/study_plan_disciplines.jsonl",
                "study_plan_data/study_plan_semester_load.csv",
                "study_plan_data/study_plan_discipline_entities.jsonl",
                "study_plan_data/study_plan_resolution_report.json",
                "study_plan_data/study_plan_curriculum_schema.json",
            ],
            metadata={
                "curriculum_rows": len(semantic["curriculum_rows"]),
                "disciplines": len(semantic["disciplines"]),
                "semester_loads": len(semantic["semester_loads"]),
                "resolved_entities": len(semantic["resolution"]["entities"]),
            },
        )
        run.stage(
            "ontology_projection",
            inputs=[
                "study_plan_data/study_plan_documents.jsonl",
                "study_plan_data/study_plan_disciplines.jsonl",
                "study_plan_data/study_plan_semester_load.csv",
            ],
            outputs=["study_plan_data/study_plan_ontology.json"],
            metadata={
                "objects": sum(
                    len(bucket) for bucket in ontology.get("objects", {}).values()
                ),
                "links": len(ontology.get("links", [])),
            },
        )
        run.stage(
            "quality_gate",
            inputs=[
                "study_plan_data/study_plan_curriculum_rows.jsonl",
                "study_plan_data/study_plan_disciplines.jsonl",
                "study_plan_data/study_plan_semester_load.csv",
            ],
            outputs=["study_plan_data/study_plan_semantic_report.json"],
            quality=semantic["report"],
        )
        report = semantic["report"]
        run.finish(
            status="succeeded" if report["verification"]["passed"] else "failed",
            quality=report,
        )
        return report
    except Exception as exc:
        run.finish(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise


__all__ = [
    "extract_semantics",
    "enrich_existing_dataset",
    "write_semantic_dataset",
    "extend_ontology_with_semantics",
    "_semantic_row",
    "_reconcile_totals",
    "_csv_semantic_rows",
    "_clean",
    "_json_value",
    "_number",
    "_number_tokens",
    "_control_tokens",
    "_control_kinds",
    "_strip_control_tokens",
    "_unique_tokens",
    "_row_kind",
    "_part_type",
    "_bbox",
    "_cell_from_csv",
    "_table_bounds",
    "_normalized_span",
    "_find_header_span",
    "_join_words",
    "_row_words",
    "_overlap",
    "_band_payload",
    "_page_words_by_key",
    "_semester_spans",
    "_control_assignments",
    "BASE_FIELD_NAMES",
    "SEMESTER_FIELD_NAMES",
]
