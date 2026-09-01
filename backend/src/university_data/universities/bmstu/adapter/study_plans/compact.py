from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain.ids import stable_id
from ..outputs.writers import write_json
from ..runtime.lineage import PipelineRun
from .ids import row_id
from .ontology import StudyPlanOntologyBuilder
from .writers import write_csv


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _compact_ontology(
    data_dir: Path, documents: list[dict[str, Any]]
) -> dict[str, Any]:
    builder = StudyPlanOntologyBuilder()
    documents_by_id = {document["document_id"]: document for document in documents}
    for document in documents:
        provenance = {
            "source_url": document.get("source_url", ""),
            "resolved_url": document.get("resolved_url", ""),
            "local_path": document.get("local_path", ""),
            "raw_dataset": "study_plan_tables.jsonl",
            "extracted_at_utc": document.get("extracted_at_utc", ""),
        }
        document_id = document["document_id"]
        builder.add_object(
            "study_plan_document",
            document_id,
            {
                "source_key": document_id,
                "local_path": document.get("local_path", ""),
                "kind": document.get("kind", ""),
                "status": document.get("status", ""),
                "source_size": document.get("source_size"),
                "source_sha256": document.get("source_sha256", ""),
                "page_count": document.get("page_count", 0),
                "table_count": document.get("table_count", 0),
                "row_count": document.get("row_count", 0),
                "cell_count": document.get("cell_count", 0),
                "raw_layout_path": document.get("raw_layout_path", ""),
            },
            provenance,
        )
        for reference in document.get("source_references", []):
            program_id = reference.get("program_id") or stable_id(
                "educational-program",
                reference.get("major_id", ""),
                reference.get("program_name", ""),
            )
            builder.add_object(
                "educational_program",
                program_id,
                {
                    "source_key": program_id,
                    "major_id": reference.get("major_id", ""),
                    "major_code": reference.get("major_code", ""),
                    "major_name": reference.get("major_name", ""),
                    "program_code": reference.get("program_code", ""),
                    "program_name": reference.get("program_name", ""),
                },
                provenance,
            )
            builder.add_link(
                "study_plan_document_for_program", document_id, program_id, provenance
            )

    tables = _read_jsonl(data_dir / "study_plan_tables.jsonl")
    for table in tables:
        document = documents_by_id[table["document_id"]]
        provenance = {
            "source_url": document.get("source_url", ""),
            "resolved_url": document.get("resolved_url", ""),
            "local_path": document.get("local_path", ""),
            "raw_dataset": "study_plan_tables.jsonl",
            "extracted_at_utc": document.get("extracted_at_utc", ""),
        }
        builder.add_object(
            "study_plan_table",
            table["id"],
            {
                "source_key": table["id"],
                "page_number": table.get("page_number"),
                "table_index": table.get("table_index"),
                "section": table.get("section", ""),
                "bbox": table.get("bbox"),
                "row_count": table.get("row_count", 0),
                "column_count": table.get("column_count", 0),
                "extraction_method": table.get("extraction_method", ""),
            },
            provenance,
        )
        builder.add_link(
            "study_plan_document_contains_table",
            table["document_id"],
            table["id"],
            provenance,
        )

    for row in _read_jsonl(data_dir / "study_plan_rows.jsonl"):
        document = documents_by_id[row["document_id"]]
        provenance = {
            "source_url": document.get("source_url", ""),
            "resolved_url": document.get("resolved_url", ""),
            "local_path": document.get("local_path", ""),
            "raw_dataset": "study_plan_rows.jsonl",
            "extracted_at_utc": document.get("extracted_at_utc", ""),
        }
        builder.add_object(
            "study_plan_row",
            row["id"],
            {
                "source_key": row["id"],
                "table_id": row["table_id"],
                "page_number": row.get("page_number"),
                "row_index": row.get("row_index"),
                "first_cell": row.get("first_cell", ""),
                "second_cell": row.get("second_cell", ""),
                "cell_count": row.get("cell_count", 0),
                "cells_dataset": "study_plan_cells.csv",
                "cells_locator": {
                    "table_id": row["table_id"],
                    "row_index": row.get("row_index"),
                },
            },
            provenance,
        )
        builder.add_link(
            "study_plan_table_contains_row", row["table_id"], row["id"], provenance
        )
    return builder.build([])


def _compact_existing_dataset(result_dir: Path) -> dict[str, Any]:
    """Remove redundant cell copies while retaining the complete cell dataset."""

    data_dir = result_dir / "study_plan_data"
    documents = _read_jsonl(data_dir / "study_plan_documents.jsonl")
    documents_by_id = {document["document_id"]: document for document in documents}
    table_path = data_dir / "study_plan_tables.jsonl"
    first_table: dict[str, Any] | None = None
    with table_path.open(encoding="utf-8") as stream:
        first_line = next((line for line in stream if line.strip()), "")
        if first_line:
            first_table = json.loads(first_line)
    report_path = data_dir / "study_plan_extraction_report.json"
    if first_table is not None and "rows" not in first_table:
        quality = json.loads(report_path.read_text(encoding="utf-8"))
        ontology_path = data_dir / "study_plan_ontology.json"
        existing_ontology = (
            json.loads(ontology_path.read_text(encoding="utf-8"))
            if ontology_path.exists()
            else {}
        )
        # The current writer already emits compact tables/rows. Preserve the
        # semantic discipline/load objects if the semantic enrichment block
        # has already extended Ontology; rebuilding only the base layer would
        # silently discard them.
        if "study_plan_discipline" not in existing_ontology.get("objects", {}):
            write_json(ontology_path, _compact_ontology(data_dir, documents))
        quality.setdefault("storage", {})["ontology_uses_cell_locator"] = True
        write_json(report_path, quality)
        return quality
    compact_table_path = data_dir / "study_plan_tables.jsonl.compact"
    compact_row_path = data_dir / "study_plan_rows.jsonl.compact"
    rows: list[dict[str, Any]] = []
    seen_tables: set[str] = set()
    ontology_builder = StudyPlanOntologyBuilder()
    table_count = 0
    cell_count = 0
    with (
        compact_table_path.open("w", encoding="utf-8") as table_output,
        compact_row_path.open("w", encoding="utf-8") as row_output,
    ):
        for table in _read_jsonl(table_path):
            if table["id"] in seen_tables:
                continue
            seen_tables.add(table["id"])
            table_count += 1
            table_rows = table.get("rows", [])
            lean_table = {
                "id": table["id"],
                "document_id": table["document_id"],
                "page_number": table.get("page_number"),
                "table_index": table.get("table_index"),
                "section": table.get("section", ""),
                "bbox": table.get("bbox"),
                "row_count": table.get("row_count", len(table_rows)),
                "column_count": table.get("column_count", 0),
                "row_ids": [
                    row_id(table["id"], row_index)
                    for row_index, _ in enumerate(table_rows)
                ],
                "extraction_method": table.get("extraction_method", ""),
            }
            table_output.write(
                json.dumps(lean_table, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
            document = documents_by_id[table["document_id"]]
            ontology_builder.build([{"document": document, "tables": [table]}])
            for row_index, cells in enumerate(table_rows):
                values = [cell.get("text", "") for cell in cells]
                cell_ids = [cell.get("id", "") for cell in cells]
                cell_count += len(cells)
                row = {
                    "id": row_id(table["id"], row_index),
                    "table_id": table["id"],
                    "document_id": table["document_id"],
                    "page_number": table.get("page_number"),
                    "section": table.get("section", ""),
                    "row_index": row_index,
                    "first_cell": values[0] if values else "",
                    "second_cell": values[1] if len(values) > 1 else "",
                    "cell_ids": cell_ids,
                    "cell_count": len(cells),
                }
                rows.append(row)
                row_output.write(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                )

    compact_rows_csv = data_dir / "study_plan_rows.csv.compact"
    write_csv(
        compact_rows_csv,
        rows,
        [
            "id",
            "table_id",
            "document_id",
            "page_number",
            "section",
            "row_index",
            "first_cell",
            "second_cell",
            "cell_ids",
            "cell_count",
        ],
    )
    compact_table_path.replace(data_dir / "study_plan_tables.jsonl")
    compact_row_path.replace(data_dir / "study_plan_rows.jsonl")
    compact_rows_csv.replace(data_dir / "study_plan_rows.csv")

    quality = json.loads(report_path.read_text(encoding="utf-8"))
    quality.setdefault("storage", {})
    quality["storage"].update(
        {
            "canonical_cell_dataset": "study_plan_cells.csv",
            "tables_and_rows_reference_cell_ids": True,
            "compacted_at": "runtime",
        }
    )
    quality.setdefault("counts", {})
    quality["counts"]["unique_tables"] = table_count
    quality["counts"]["unique_rows"] = len(rows)
    quality["counts"]["cells"] = cell_count
    write_json(report_path, quality)
    write_json(
        data_dir / "study_plan_ontology.json",
        {"schema_version": "2.0", **ontology_builder.build([])},
    )
    # A legacy table compaction must not silently erase the semantic Ontology
    # layer created by university-data extract_semantics. Rebuild it from the
    # compacted source datasets when that layer already exists.
    if (data_dir / "study_plan_disciplines.jsonl").exists() and (
        data_dir / "study_plan_semester_load.csv"
    ).exists():
        from .semantics import enrich_existing_dataset

        enrich_existing_dataset(result_dir)
    main_report = result_dir / "parse_report.json"
    if main_report.exists():
        main = json.loads(main_report.read_text(encoding="utf-8"))
        main["study_plan_extraction"] = quality
        write_json(main_report, main)
    return quality


def compact_existing_dataset(result_dir: Path) -> dict[str, Any]:
    """Compact derived projections and record the operation as a pipeline run."""

    run = PipelineRun(result_dir, "compact_study_plans")
    try:
        quality = _compact_existing_dataset(result_dir)
        run.stage(
            "compact_projections",
            inputs=[
                "study_plan_data/study_plan_tables.jsonl",
                "study_plan_data/study_plan_rows.jsonl",
                "study_plan_data/study_plan_cells.csv",
            ],
            outputs=[
                "study_plan_data/study_plan_tables.jsonl",
                "study_plan_data/study_plan_rows.jsonl",
                "study_plan_data/study_plan_rows.csv",
                "study_plan_data/study_plan_ontology.json",
            ],
            quality=quality,
        )
        run.finish(
            status="succeeded"
            if quality.get("verification", {}).get("passed", True)
            else "failed",
            quality=quality,
        )
        return quality
    except Exception as exc:
        run.finish(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
