# mypy: ignore-errors

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .ids import discipline_id, row_id, semester_load_id
from .semantic_geometry import (
    band_payload,
    control_assignments,
    row_words,
    semester_spans,
)
from .semantic_schema import BASE_FIELD_NAMES, SEMESTER_FIELD_NAMES
from .semantic_shared import clean

NUMBER_RE = re.compile(r"[-+]?\d+(?:[\.,]\d+)?")
CONTROL_RE = re.compile(r"ДЗчт|РЭкз|Зчт|Экз|ГЭК|КуР|КуП|ЭК", re.IGNORECASE)

CONTROL_KIND = {
    "зчт": "credit",
    "дзчт": "graded_credit",
    "экз": "exam",
    "рэкз": "rated_exam",
    "гэк": "state_attestation",
    "кур": "coursework",
    "куп": "course_project",
    "эк": "other_control",
}


def number_tokens(value: str) -> list[str]:
    return NUMBER_RE.findall(value.replace("−", "-"))


def number(value: str) -> int | float | None:
    tokens = number_tokens(value)
    if not tokens:
        return None
    parsed = tokens[0].replace(",", ".")
    try:
        numeric = float(parsed)
    except ValueError:
        return None
    return int(numeric) if numeric.is_integer() else numeric


def control_tokens(value: str) -> list[str]:
    tokens: list[str] = []
    for match in CONTROL_RE.finditer(value):
        token = match.group(0)
        normalized = token.casefold()
        if normalized not in {item.casefold() for item in tokens}:
            tokens.append(token)
    return tokens


def strip_control_tokens(value: str) -> str:
    return clean(CONTROL_RE.sub(" ", value or ""))


def unique_tokens(tokens: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(token)
    return result


def control_kinds(tokens: list[str]) -> list[str]:
    kinds: list[str] = []
    for token in tokens:
        key = token.casefold().replace("х", "x")
        kind = CONTROL_KIND.get(key)
        if kind and kind not in kinds:
            kinds.append(kind)
    return kinds


def row_kind(code: str, name: str) -> str:
    normalized = name.casefold()
    if re.fullmatch(r"\d+", code):
        return "discipline"
    if "дисциплины (модули)" in normalized:
        return "cycle"
    if "обязательн" in normalized:
        return "mandatory_group"
    if (
        "вариативн" in normalized
        or "по выбору" in normalized
        or "электив" in normalized
        or "факультатив" in normalized
    ):
        return "elective_group"
    if code or name:
        return "section"
    return "empty"


def part_type(name: str, current: str) -> str:
    normalized = name.casefold()
    if (
        "вариативн" in normalized
        or "по выбору" in normalized
        or "электив" in normalized
        or "факультатив" in normalized
    ):
        return "elective"
    if "обязательн" in normalized:
        return "mandatory"
    return current


def semantic_row(
    table: dict[str, Any],
    row_index: int,
    cells: list[dict[str, Any]],
    schema: dict[str, Any] | None,
    page_words: dict[str, dict[str, Any]],
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    cells = sorted(cells, key=lambda cell: cell["column_index"])
    source_row_id = row_id(table["id"], row_index)
    source_cell_ids = [cell["id"] for cell in cells]
    row_record: dict[str, Any] = {
        "id": source_row_id,
        "document_id": table.get("document_id", ""),
        "table_id": table.get("id", ""),
        "page_number": table.get("page_number"),
        "row_index": row_index,
        "source_cells_dataset": "study_plan_cells.csv",
        "source_cell_ids": source_cell_ids,
        "raw_cell_count": len(cells),
        "extraction_warnings": [],
    }
    if row_index < 4:
        row_record.update(
            {"row_kind": "header", "code": "", "name": "", "department": ""}
        )
        return row_record, None, []
    if schema is None:
        row_record.update(
            {"row_kind": "unresolved_schema", "code": "", "name": "", "department": ""}
        )
        row_record["extraction_warnings"].append(
            "Для документа не найден заголовок curriculum-таблицы"
        )
        return row_record, None, []

    words = row_words(cells, page_words)
    raw_base: dict[str, str] = {}
    base: dict[str, Any] = {}
    source_word_ids: set[str] = set()
    for field in BASE_FIELD_NAMES:
        span = schema.get("base_spans", {}).get(field)
        payload = (
            band_payload(cells, words, table, span)
            if span
            else {"text": "", "cell_ids": [], "word_ids": []}
        )
        raw_base[field] = payload["text"]
        source_word_ids.update(payload["word_ids"])
        if field in {"code", "name", "department"}:
            base[field] = payload["text"]
        else:
            base[field] = number(payload["text"])
            if len(number_tokens(payload["text"])) > 1:
                row_record["extraction_warnings"].append(
                    f"В поле {field} обнаружено несколько чисел: {payload['text']}"
                )

    code = clean(base.get("code", ""))
    name = clean(base.get("name", ""))
    department = clean(base.get("department", ""))
    kind = row_kind(code, name)
    if (
        kind in {"cycle", "mandatory_group", "elective_group", "section"}
        and name
        and (not state["section_path"] or state["section_path"][-1] != name)
    ):
        state["section_path"].append(name)
    current_part_type = part_type(name, state.get("part_type", "unknown"))
    if kind in {"mandatory_group", "elective_group"}:
        state["part_type"] = current_part_type
    row_record.update(
        {
            "row_kind": kind,
            "code": code,
            "name": name,
            "department": department,
            "part_type": current_part_type,
            "section_path": list(state["section_path"]),
            "raw_base": raw_base,
            "workload": {
                "credits": base.get("total_credits"),
                "hours": base.get("total_hours"),
                "audited_hours": base.get("audited_hours"),
            },
            "class_hours": {
                "lecture": base.get("lecture_hours"),
                "seminar": base.get("seminar_hours"),
                "lab": base.get("lab_hours"),
                "independent_or_other": base.get("independent_or_other_hours"),
            },
            "source_word_ids": sorted(source_word_ids),
        }
    )
    if kind != "discipline":
        return row_record, None, []

    discipline_identifier = discipline_id(
        table["id"],
        code,
        name,
        department,
        current_part_type,
        state["section_path"],
    )
    loads: list[dict[str, Any]] = []
    assignments = control_assignments(
        table,
        cells,
        schema,
        words,
        len(SEMESTER_FIELD_NAMES),
        control_tokens,
    )
    for semester, span in semester_spans(schema):
        field_payloads: dict[str, dict[str, Any]] = {}
        for offset, field in enumerate(SEMESTER_FIELD_NAMES):
            start = span[0] + (span[1] - span[0]) * offset / 5
            end = span[0] + (span[1] - span[0]) * (offset + 1) / 5
            field_payloads[field] = band_payload(cells, words, table, [start, end])
        raw_bands = {
            field: field_payloads[field]["text"] for field in SEMESTER_FIELD_NAMES
        }
        raw = {
            field: strip_control_tokens(raw_bands[field])
            if field != "control"
            else raw_bands[field]
            for field in SEMESTER_FIELD_NAMES
        }
        assigned_controls = assignments.get(semester, [])
        assigned_tokens = unique_tokens(item["token"] for item in assigned_controls)
        control_residual = strip_control_tokens(raw_bands["control"])
        if words:
            raw["control"] = clean(
                " ".join(
                    value for value in [control_residual, *assigned_tokens] if value
                )
            )
        normalization_notes = [
            f"control_token_removed_from_{field}"
            for field in SEMESTER_FIELD_NAMES[:-1]
            if raw_bands[field] != raw[field]
        ]
        band_control_tokens = unique_tokens(control_tokens(raw_bands["control"]))
        numeric_band_control_tokens = unique_tokens(
            token
            for field in SEMESTER_FIELD_NAMES[:-1]
            for token in control_tokens(raw_bands[field])
        )
        if assigned_tokens and (
            {token.casefold() for token in band_control_tokens}
            != {token.casefold() for token in assigned_tokens}
            or numeric_band_control_tokens
            or any(
                item.get("word_id") not in field_payloads["control"]["word_ids"]
                for item in assigned_controls
            )
        ):
            normalization_notes.append("control_reassigned_by_word_start")
        controls = control_tokens(raw["control"])
        load_identifier = semester_load_id(discipline_identifier, semester)
        load = {
            "id": load_identifier,
            "discipline_id": discipline_identifier,
            "document_id": table.get("document_id", ""),
            "table_id": table.get("id", ""),
            "page_number": table.get("page_number"),
            "row_index": row_index,
            "source_row_id": source_row_id,
            "code": code,
            "name": name,
            "semester": semester,
            "weeks": schema.get("semester_headers", {})
            .get(str(semester), schema.get("semester_headers", {}).get(semester, {}))
            .get("weeks"),
            "active": any(raw.values()),
            "has_numeric_load": any(
                number(raw[field]) is not None for field in SEMESTER_FIELD_NAMES[:-1]
            ),
            "credits": number(raw["credits"]),
            "hours": number(raw["hours"]),
            "audited_hours": number(raw["audited_hours"]),
            "independent_or_other_hours": number(raw["independent_or_other_hours"]),
            "control": raw["control"],
            "control_tokens": controls,
            "control_kinds": control_kinds(controls),
            "raw": raw,
            "raw_bands": raw_bands,
            "normalization_notes": normalization_notes,
            "source_cell_ids": sorted(
                {
                    cell_id
                    for payload in field_payloads.values()
                    for cell_id in payload["cell_ids"]
                }
            ),
            "source_word_ids": sorted(
                {
                    word_id
                    for payload in field_payloads.values()
                    for word_id in payload["word_ids"]
                }
                | {item["word_id"] for item in assigned_controls if item.get("word_id")}
            ),
        }
        if any(
            len(number_tokens(raw[field])) > 1 for field in SEMESTER_FIELD_NAMES[:-1]
        ):
            row_record["extraction_warnings"].append(
                f"В семестре {semester} объединены числовые значения"
            )
        loads.append(load)

    discipline = {
        "id": discipline_identifier,
        "source_row_id": source_row_id,
        "document_id": table.get("document_id", ""),
        "table_id": table.get("id", ""),
        "page_number": table.get("page_number"),
        "row_index": row_index,
        "code": code,
        "name": name,
        "department": department,
        "part_type": current_part_type,
        "section_path": list(state["section_path"]),
        "workload": row_record["workload"],
        "class_hours": row_record["class_hours"],
        "raw_base": raw_base,
        "semester_count": len(loads),
        "semester_load_ids": [load["id"] for load in loads],
        "source_cells_dataset": "study_plan_cells.csv",
        "source_cell_ids": source_cell_ids,
        "extraction_warnings": row_record["extraction_warnings"],
    }
    row_record["discipline_id"] = discipline_identifier
    row_record["semester_load_ids"] = discipline["semester_load_ids"]
    return row_record, discipline, loads
