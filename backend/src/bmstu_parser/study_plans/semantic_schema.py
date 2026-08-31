from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
import re
from typing import Any, Iterator

from .semantic_geometry import cell_from_csv, find_header_span, table_bounds
from .semantic_shared import clean


SEMESTER_RE = re.compile(
    r"(?:(?:семестр)\s*)?(\d+)\s*[-–—]\s*(\d+)\s*недель",
    re.IGNORECASE,
)

BASE_FIELD_NAMES = (
    "code",
    "name",
    "department",
    "total_credits",
    "total_hours",
    "audited_hours",
    "lecture_hours",
    "seminar_hours",
    "lab_hours",
    "independent_or_other_hours",
)

SEMESTER_FIELD_NAMES = (
    "credits",
    "hours",
    "audited_hours",
    "independent_or_other_hours",
    "control",
)


def discover_schema(
    table: dict[str, Any],
    header_rows: dict[int, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    row_zero = header_rows.get(0, [])
    semester_cells = [
        cell
        for cell in row_zero
        if SEMESTER_RE.search(clean(cell.get("text", ""))) and cell.get("bbox")
    ]
    if not semester_cells:
        return None
    x0, x1 = table_bounds(table, header_rows)
    width = max(x1 - x0, 1.0)
    semester_headers: dict[int, dict[str, Any]] = {}
    for cell in semester_cells:
        text = clean(cell.get("text", ""))
        for match in SEMESTER_RE.finditer(text):
            number = int(match.group(1))
            semester_headers[number] = {
                "label": clean(match.group(0)),
                "weeks": int(match.group(2)) if match.group(2) else None,
            }
    if not semester_headers:
        return None
    semester_start = min(float(cell["bbox"]["x0"]) for cell in semester_cells)
    semester_start_rel = max(0.0, min(1.0, (semester_start - x0) / width))
    semester_count = max(semester_headers)
    warnings: list[str] = []
    if sorted(semester_headers) != list(range(1, semester_count + 1)):
        warnings.append("В заголовке отсутствует один или несколько номеров семестров")

    row_two = header_rows.get(2, [])
    row_three = header_rows.get(3, [])
    base_spans: dict[str, list[float] | None] = {}
    base_spans["code"] = find_header_span(
        row_zero, lambda value: value == "шифр", x0, width
    )
    base_spans["name"] = find_header_span(
        row_zero, lambda value: "наименование" in value, x0, width
    )
    base_spans["department"] = find_header_span(
        row_zero, lambda value: value == "кафедра", x0, width
    )
    header_predicates = {
        "total_credits": lambda value: "общая, з.е." in value,
        "total_hours": lambda value: "общая, час" in value,
        "audited_hours": lambda value: "аудит" in value and "час" in value,
        "lecture_hours": lambda value: value == "лек",
        "seminar_hours": lambda value: value == "сем",
        "lab_hours": lambda value: value == "лаб",
        "independent_or_other_hours": lambda value: value == "сам" or "иные" in value,
    }
    for field, predicate in header_predicates.items():
        span = find_header_span(row_two, predicate, x0, width)
        if span is None:
            span = find_header_span(row_three, predicate, x0, width)
        base_spans[field] = span

    missing_base = [
        field for field in BASE_FIELD_NAMES if base_spans.get(field) is None
    ]
    if missing_base:
        warnings.append(f"Не найден заголовок базовых полей: {', '.join(missing_base)}")
    return {
        "document_id": table.get("document_id", ""),
        "source_table_id": table.get("id", ""),
        "source_page_number": table.get("page_number"),
        "table_x0": x0,
        "table_x1": x1,
        "semester_start_rel": semester_start_rel,
        "semester_end_rel": 1.0,
        "semester_count": semester_count,
        "semester_headers": semester_headers,
        "base_spans": base_spans,
        "warnings": warnings,
    }


def discover_schemas(
    tables: list[dict[str, Any]], cells_path: Path
) -> dict[str, dict[str, Any]]:
    curriculum_ids = {
        table["id"] for table in tables if table.get("section") == "curriculum"
    }
    header_rows: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    with cells_path.open(encoding="utf-8-sig", newline="") as stream:
        for csv_row in csv.DictReader(stream):
            table_id = csv_row.get("table_id", "")
            if table_id not in curriculum_ids:
                continue
            row_index = int(csv_row.get("row_index") or 0)
            if row_index < 4:
                header_rows[table_id][row_index].append(cell_from_csv(csv_row))
    schemas: dict[str, dict[str, Any]] = {}
    for table in tables:
        if table.get("section") != "curriculum":
            continue
        candidate = discover_schema(table, header_rows.get(table["id"], {}))
        if candidate is not None and table.get("document_id") not in schemas:
            schemas[table["document_id"]] = candidate
    return schemas


def iter_curriculum_table_rows(
    cells_path: Path,
    curriculum_ids: set[str],
) -> Iterator[tuple[str, dict[int, list[dict[str, Any]]]]]:
    current_table_id = ""
    current_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    with cells_path.open(encoding="utf-8-sig", newline="") as stream:
        for csv_row in csv.DictReader(stream):
            table_id = csv_row.get("table_id", "")
            if table_id not in curriculum_ids:
                continue
            if current_table_id and table_id != current_table_id:
                yield current_table_id, dict(current_rows)
                current_rows = defaultdict(list)
            current_table_id = table_id
            current_rows[int(csv_row.get("row_index") or 0)].append(
                cell_from_csv(csv_row)
            )
    if current_table_id:
        yield current_table_id, dict(current_rows)
