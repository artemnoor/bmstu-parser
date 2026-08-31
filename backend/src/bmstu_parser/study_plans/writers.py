from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from ..outputs.writers import write_json
from ..runtime.atomic import atomic_text_writer
from ..transform.text import json_cell, safe_filename
from .ids import row_id


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with atomic_text_writer(path, encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")


def _all_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for result in results:
        for table in result.get("tables", []):
            for row_index, cells in enumerate(table.get("rows", [])):
                values = [cell.get("text", "") for cell in cells]
                rows.append(
                    {
                        "id": row_id(table["id"], row_index),
                        "table_id": table["id"],
                        "document_id": table["document_id"],
                        "page_number": table.get("page_number"),
                        "section": table.get("section", ""),
                        "row_index": row_index,
                        "first_cell": values[0] if values else "",
                        "second_cell": values[1] if len(values) > 1 else "",
                        "cell_ids": [cell.get("id", "") for cell in cells],
                        "cell_count": len(cells),
                    }
                )
    return rows


def _all_cells(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cells = []
    for result in results:
        for table in result.get("tables", []):
            for row in table.get("rows", []):
                for cell in row:
                    cells.append(
                        {
                            "id": cell.get("id", ""),
                            "table_id": cell.get("table_id", ""),
                            "document_id": table.get("document_id", ""),
                            "page_number": table.get("page_number"),
                            "section": table.get("section", ""),
                            "row_index": cell.get("row_index"),
                            "column_index": cell.get("column_index"),
                            "text": cell.get("text", ""),
                            "bbox": json_cell(cell.get("bbox")),
                            "word_ids": json_cell(cell.get("word_ids", [])),
                            "cell_kind": cell.get("cell_kind", ""),
                        }
                    )
    return cells


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with atomic_text_writer(path, encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_extraction_dataset(
    output_dir: Path,
    results: list[dict[str, Any]],
    quality: dict[str, Any],
    ontology: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_layout_dir = output_dir / "raw_layout"
    raw_layout_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        document = result["document"]
        layout_path = raw_layout_dir / f"{safe_filename(document['document_id'])}.txt"
        with atomic_text_writer(layout_path, encoding="utf-8") as stream:
            stream.write(result.get("layout_text", ""))
        document["raw_layout_path"] = str(layout_path.relative_to(output_dir))

    documents = [result["document"] for result in results]
    pages = [page | {"document_id": result["document"]["document_id"]} for result in results for page in result.get("pages", [])]
    tables = [
        {
            "id": table["id"],
            "document_id": table["document_id"],
            "page_number": table.get("page_number"),
            "table_index": table.get("table_index"),
            "section": table.get("section", ""),
            "bbox": table.get("bbox"),
            "row_count": table.get("row_count", 0),
            "column_count": table.get("column_count", 0),
            "row_ids": [row_id(table["id"], row_index) for row_index, _ in enumerate(table.get("rows", []))],
            "extraction_method": table.get("extraction_method", ""),
        }
        for result in results
        for table in result.get("tables", [])
    ]
    rows = _all_rows(results)
    cells = _all_cells(results)
    dataset_quality = {
        **quality,
        "counts": {**quality.get("counts", {})},
        "storage": {
            **quality.get("storage", {}),
            "canonical_cell_dataset": "study_plan_cells.csv",
            "tables_and_rows_reference_cell_ids": True,
            "ontology_uses_cell_locator": True,
            "materialization_mode": "compact_projections_with_full_cell_dataset",
        },
    }
    dataset_quality["counts"].update(
        {
            "unique_tables": len({table["id"] for result in results for table in result.get("tables", [])}),
            "unique_rows": len({row["id"] for row in rows}),
        }
    )
    write_jsonl(output_dir / "study_plan_documents.jsonl", documents)
    write_jsonl(output_dir / "study_plan_pages.jsonl", pages)
    write_jsonl(output_dir / "study_plan_tables.jsonl", tables)
    write_jsonl(output_dir / "study_plan_rows.jsonl", rows)
    write_csv(
        output_dir / "study_plan_cells.csv",
        cells,
        ["id", "table_id", "document_id", "page_number", "section", "row_index", "column_index", "text", "bbox", "word_ids", "cell_kind"],
    )
    write_csv(
        output_dir / "study_plan_rows.csv",
        [
            {
                "id": row["id"],
                "table_id": row["table_id"],
                "document_id": row["document_id"],
                "page_number": row["page_number"],
                "section": row["section"],
                "row_index": row["row_index"],
                "first_cell": row["first_cell"],
                "second_cell": row["second_cell"],
                "cell_ids": json_cell(row["cell_ids"]),
                "cell_count": row["cell_count"],
            }
            for row in rows
        ],
        ["id", "table_id", "document_id", "page_number", "section", "row_index", "first_cell", "second_cell", "cell_ids", "cell_count"],
    )
    write_json(output_dir / "study_plan_ontology.json", {"schema_version": "2.0", **ontology})
    write_json(output_dir / "study_plan_extraction_report.json", {"schema_version": "2.0", **dataset_quality})

    main_report = output_dir.parent / "parse_report.json"
    if main_report.exists():
        current = json.loads(main_report.read_text(encoding="utf-8"))
        current["study_plan_extraction"] = dataset_quality
        write_json(main_report, current)
