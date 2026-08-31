from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator

from ..domain.ids import link_id
from ..outputs.writers import write_json
from ..runtime.lineage import PipelineRun
from .ids import discipline_id, row_id, semester_load_id
from .resolution import resolve_disciplines
from .rules import validate_curriculum_contract
from .writers import write_csv, write_jsonl


SEMESTER_RE = re.compile(
    r"(?:(?:семестр)\s*)?(\d+)\s*[-–—]\s*(\d+)\s*недель",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"[-+]?\d+(?:[\.,]\d+)?")
CONTROL_RE = re.compile(r"ДЗчт|РЭкз|Зчт|Экз|ГЭК|КуР|КуП|ЭК", re.IGNORECASE)

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

CONTROL_KIND = {
    "зчт": "credit",
    "дзчт": "graded_credit",
    "экз": "exam",
    "рэкз": "rated_exam",
    "гэк": "state_attestation",
    "кур": "coursework",
    "куп": "course_project",
    # The source uses this abbreviation once.  Preserve it as a known
    # control token without inventing a more specific meaning.
    "эк": "other_control",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _json_value(value: str, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _bbox(value: Any) -> dict[str, float] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = _json_value(value, None)
        return parsed if isinstance(parsed, dict) else None
    return None


def _cell_from_csv(row: dict[str, str]) -> dict[str, Any]:
    return {
        "id": row.get("id", ""),
        "column_index": int(row.get("column_index") or 0),
        "row_index": int(row.get("row_index") or 0),
        "text": row.get("text", ""),
        "bbox": _bbox(row.get("bbox", "")),
        "word_ids": _json_value(row.get("word_ids", ""), []),
    }


def _table_bounds(table: dict[str, Any], rows: dict[int, list[dict[str, Any]]]) -> tuple[float, float]:
    table_bbox = _bbox(table.get("bbox")) or {}
    x0 = table_bbox.get("x0")
    x1 = table_bbox.get("x1")
    if x0 is not None and x1 is not None and x1 > x0:
        return float(x0), float(x1)
    boxes = [
        cell["bbox"]
        for row in rows.values()
        for cell in row
        if cell.get("bbox") and cell["bbox"].get("x0") is not None and cell["bbox"].get("x1") is not None
    ]
    if not boxes:
        return 0.0, 1.0
    return min(float(box["x0"]) for box in boxes), max(float(box["x1"]) for box in boxes)


def _normalized_span(box: dict[str, float] | None, x0: float, width: float) -> list[float] | None:
    if not box or width <= 0:
        return None
    left = max(0.0, min(1.0, (float(box["x0"]) - x0) / width))
    right = max(left, min(1.0, (float(box["x1"]) - x0) / width))
    return [left, right]


def _find_header_span(cells: Iterable[dict[str, Any]], predicate: Any, x0: float, width: float) -> list[float] | None:
    candidates = [cell for cell in cells if predicate(_clean(cell.get("text", "")).lower()) and cell.get("bbox")]
    if not candidates:
        return None
    candidate = min(candidates, key=lambda cell: float(cell["bbox"]["x0"]))
    return _normalized_span(candidate["bbox"], x0, width)


def _discover_schema(table: dict[str, Any], header_rows: dict[int, list[dict[str, Any]]]) -> dict[str, Any] | None:
    row_zero = header_rows.get(0, [])
    semester_cells = [
        cell for cell in row_zero if SEMESTER_RE.search(_clean(cell.get("text", ""))) and cell.get("bbox")
    ]
    if not semester_cells:
        return None
    x0, x1 = _table_bounds(table, header_rows)
    width = max(x1 - x0, 1.0)
    semester_headers: dict[int, dict[str, Any]] = {}
    for cell in semester_cells:
        text = _clean(cell.get("text", ""))
        for match in SEMESTER_RE.finditer(text):
            number = int(match.group(1))
            semester_headers[number] = {
                "label": _clean(match.group(0)),
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
    base_spans: dict[str, list[float]] = {}
    base_spans["code"] = _find_header_span(row_zero, lambda value: value == "шифр", x0, width)
    base_spans["name"] = _find_header_span(row_zero, lambda value: "наименование" in value, x0, width)
    base_spans["department"] = _find_header_span(row_zero, lambda value: value == "кафедра", x0, width)
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
        span = _find_header_span(row_two, predicate, x0, width)
        if span is None:
            span = _find_header_span(row_three, predicate, x0, width)
        base_spans[field] = span

    missing_base = [field for field in BASE_FIELD_NAMES if base_spans.get(field) is None]
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


def _discover_schemas(tables: list[dict[str, Any]], cells_path: Path) -> dict[str, dict[str, Any]]:
    curriculum_ids = {table["id"] for table in tables if table.get("section") == "curriculum"}
    header_rows: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    with cells_path.open(encoding="utf-8-sig", newline="") as stream:
        for csv_row in csv.DictReader(stream):
            table_id = csv_row.get("table_id", "")
            if table_id not in curriculum_ids:
                continue
            row_index = int(csv_row.get("row_index") or 0)
            if row_index < 4:
                header_rows[table_id][row_index].append(_cell_from_csv(csv_row))
    schemas: dict[str, dict[str, Any]] = {}
    for table in tables:
        if table.get("section") != "curriculum":
            continue
        candidate = _discover_schema(table, header_rows.get(table["id"], {}))
        if candidate is not None and table.get("document_id") not in schemas:
            schemas[table["document_id"]] = candidate
    return schemas


def _iter_curriculum_table_rows(
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
            current_rows[int(csv_row.get("row_index") or 0)].append(_cell_from_csv(csv_row))
    if current_table_id:
        yield current_table_id, dict(current_rows)


def _join_words(words: list[dict[str, Any]]) -> str:
    if not words:
        return ""
    ordered = sorted(words, key=lambda word: (float(word.get("top", 0)), float(word.get("x0", 0))))
    lines: list[list[dict[str, Any]]] = []
    for word in ordered:
        if not lines or abs(float(word.get("top", 0)) - float(lines[-1][0].get("top", 0))) > 1.6:
            lines.append([word])
        else:
            lines[-1].append(word)
    return "\n".join(" ".join(str(word.get("text", "")) for word in line) for line in lines).strip()


def _row_words(cells: list[dict[str, Any]], page_words: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    identifiers = {word_id for cell in cells for word_id in cell.get("word_ids", [])}
    return sorted(
        (page_words[word_id] for word_id in identifiers if word_id in page_words),
        key=lambda word: (float(word.get("top", 0)), float(word.get("x0", 0)), str(word.get("id", ""))),
    )


def _overlap(left: float, right: float, other_left: float, other_right: float) -> bool:
    return min(right, other_right) - max(left, other_left) > 0.1


def _band_payload(
    cells: list[dict[str, Any]],
    words: list[dict[str, Any]],
    table: dict[str, Any],
    span: list[float],
) -> dict[str, Any]:
    table_x0, table_x1 = _table_bounds(table, {0: cells})
    width = max(table_x1 - table_x0, 1.0)
    left = table_x0 + span[0] * width
    right = table_x0 + span[1] * width
    selected_words = [
        word
        for word in words
        if left - 0.15 <= (float(word.get("x0", 0)) + float(word.get("x1", 0))) / 2 <= right + 0.15
    ]
    source_cells = [
        cell["id"]
        for cell in cells
        if cell.get("bbox")
        and _overlap(left, right, float(cell["bbox"]["x0"]), float(cell["bbox"]["x1"]))
    ]
    text = _join_words(selected_words)
    # A PDF grid cell can span two logical fields.  Falling back to the
    # whole cell text when the word itself is outside the current band
    # duplicates that text in neighbouring semantic fields.  The canonical
    # PDF word layer is authoritative whenever it is available; cell fallback
    # is only needed for sources without word coordinates.
    if not text and not words:
        fallback = [
            cell.get("text", "")
            for cell in cells
            if cell.get("bbox")
            and left - 0.15 <= (float(cell["bbox"]["x0"]) + float(cell["bbox"]["x1"])) / 2 <= right + 0.15
            and _clean(cell.get("text", ""))
        ]
        text = " ".join(fallback)
    return {
        "text": _clean(text),
        "cell_ids": sorted(set(source_cells)),
        "word_ids": sorted({str(word.get("id", "")) for word in selected_words if word.get("id")}),
    }


def _number_tokens(value: str) -> list[str]:
    return NUMBER_RE.findall(value.replace("−", "-"))


def _number(value: str) -> int | float | None:
    tokens = _number_tokens(value)
    if not tokens:
        return None
    parsed = tokens[0].replace(",", ".")
    try:
        number = float(parsed)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _control_tokens(value: str) -> list[str]:
    tokens = []
    for match in CONTROL_RE.finditer(value):
        token = match.group(0)
        normalized = token.casefold()
        if normalized not in {item.casefold() for item in tokens}:
            tokens.append(token)
    return tokens


def _strip_control_tokens(value: str) -> str:
    return _clean(CONTROL_RE.sub(" ", value or ""))


def _unique_tokens(tokens: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(token)
    return result


def _control_kinds(tokens: list[str]) -> list[str]:
    kinds = []
    for token in tokens:
        key = token.casefold().replace("х", "x")
        kind = CONTROL_KIND.get(key)
        if kind and kind not in kinds:
            kinds.append(kind)
    return kinds


def _row_kind(code: str, name: str) -> str:
    normalized = name.casefold()
    if re.fullmatch(r"\d+", code):
        return "discipline"
    if "дисциплины (модули)" in normalized:
        return "cycle"
    if "обязательн" in normalized:
        return "mandatory_group"
    if "вариативн" in normalized or "по выбору" in normalized or "электив" in normalized or "факультатив" in normalized:
        return "elective_group"
    if code or name:
        return "section"
    return "empty"


def _part_type(name: str, current: str) -> str:
    normalized = name.casefold()
    if "вариативн" in normalized or "по выбору" in normalized or "электив" in normalized or "факультатив" in normalized:
        return "elective"
    if "обязательн" in normalized:
        return "mandatory"
    return current


def _page_words_by_key(data_dir: Path) -> dict[tuple[str, int], dict[str, dict[str, Any]]]:
    pages: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for page in _read_jsonl(data_dir / "study_plan_pages.jsonl"):
        key = (page.get("document_id", ""), int(page.get("page_number") or 0))
        pages[key] = {str(word.get("id")): word for word in page.get("words", []) if word.get("id")}
    return pages


def _semester_spans(schema: dict[str, Any]) -> list[tuple[int, list[float]]]:
    start = float(schema["semester_start_rel"])
    end = float(schema["semester_end_rel"])
    count = int(schema["semester_count"])
    width = (end - start) / max(count, 1)
    return [(semester, [start + (semester - 1) * width, start + semester * width]) for semester in range(1, count + 1)]


def _control_assignments(
    table: dict[str, Any],
    cells: list[dict[str, Any]],
    schema: dict[str, Any],
    words: list[dict[str, Any]],
) -> dict[int, list[dict[str, str]]]:
    """Assign control tokens to semester control bands using PDF word starts.

    Some BMSTU PDFs contain a single physical cell spanning a semester's
    control column and the next empty column.  Its text is still a real PDF
    word, but its bounding box centre can fall into the next band.  The word's
    left edge is the stable anchor: it starts at the logical control column in
    both the ordinary and merged-cell cases.  This is deterministic source
    parsing, not text classification.
    """

    if not words:
        return {}
    table_x0, table_x1 = _table_bounds(table, {0: cells})
    table_width = max(table_x1 - table_x0, 1.0)
    semester_start = table_x0 + float(schema["semester_start_rel"]) * table_width
    control_bands: list[tuple[int, float, float]] = []
    for semester, span in _semester_spans(schema):
        left = table_x0 + span[0] * table_width
        right = table_x0 + span[1] * table_width
        field_width = (right - left) / len(SEMESTER_FIELD_NAMES)
        control_bands.append((semester, left + field_width * 4, right))

    assignments: dict[int, list[dict[str, str]]] = defaultdict(list)
    for word in words:
        anchor = float(word.get("x0", 0))
        if anchor < semester_start - 1.0:
            continue
        tokens = _control_tokens(str(word.get("text", "")))
        if not tokens:
            continue

        def distance(item: tuple[int, float, float]) -> float:
            _semester, left, right = item
            if left <= anchor <= right:
                return 0.0
            return min(abs(anchor - left), abs(anchor - right))

        semester = min(control_bands, key=distance)[0]
        for token in tokens:
            assignments[semester].append({"token": token, "word_id": str(word.get("id", ""))})
    return assignments


def _reconcile_totals(disciplines: list[dict[str, Any]], loads: list[dict[str, Any]]) -> dict[str, Any]:
    sums: dict[str, Counter[str]] = defaultdict(Counter)
    active: Counter[str] = Counter()
    for load in loads:
        identifier = load["discipline_id"]
        if load.get("has_numeric_load"):
            active[identifier] += 1
        for field in ("credits", "hours", "audited_hours", "independent_or_other_hours"):
            value = load.get(field)
            if value is not None:
                sums[identifier][field] += float(value)
    exact = 0
    unallocated: list[dict[str, Any]] = []
    active_mismatches: list[dict[str, Any]] = []
    for discipline in disciplines:
        identifier = discipline["id"]
        expected = {
            "credits": discipline["workload"].get("credits"),
            "hours": discipline["workload"].get("hours"),
            "audited_hours": discipline["workload"].get("audited_hours"),
            "independent_or_other_hours": discipline["class_hours"].get("independent_or_other"),
        }
        differences = {
            field: sums[identifier][field] - float(value)
            for field, value in expected.items()
            if value is not None and abs(sums[identifier][field] - float(value)) > 0.01
        }
        if not differences:
            exact += 1
            continue
        item = {
            "discipline_id": identifier,
            "code": discipline["code"],
            "name": discipline["name"],
            "differences": differences,
            "active_semester_count": active[identifier],
        }
        if active[identifier] == 0:
            unallocated.append(item)
        else:
            active_mismatches.append(item)
    return {
        "checked": len(disciplines),
        "exact": exact,
        "unallocated_total_without_semester_rows": len(unallocated),
        "active_semester_mismatches": len(active_mismatches),
        "examples": (unallocated + active_mismatches)[:20],
    }


def _semantic_row(
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
        row_record.update({"row_kind": "header", "code": "", "name": "", "department": ""})
        return row_record, None, []
    if schema is None:
        row_record.update({"row_kind": "unresolved_schema", "code": "", "name": "", "department": ""})
        row_record["extraction_warnings"].append("Для документа не найден заголовок curriculum-таблицы")
        return row_record, None, []

    words = _row_words(cells, page_words)
    raw_base: dict[str, str] = {}
    base: dict[str, Any] = {}
    source_word_ids: set[str] = set()
    for field in BASE_FIELD_NAMES:
        span = schema.get("base_spans", {}).get(field)
        payload = _band_payload(cells, words, table, span) if span else {"text": "", "cell_ids": [], "word_ids": []}
        raw_base[field] = payload["text"]
        source_word_ids.update(payload["word_ids"])
        if field in {"code", "name", "department"}:
            base[field] = payload["text"]
        else:
            base[field] = _number(payload["text"])
            if len(_number_tokens(payload["text"])) > 1:
                row_record["extraction_warnings"].append(f"В поле {field} обнаружено несколько чисел: {payload['text']}")

    code = _clean(base.get("code", ""))
    name = _clean(base.get("name", ""))
    department = _clean(base.get("department", ""))
    kind = _row_kind(code, name)
    if kind in {"cycle", "mandatory_group", "elective_group", "section"} and name:
        if not state["section_path"] or state["section_path"][-1] != name:
            state["section_path"].append(name)
    current_part_type = _part_type(name, state.get("part_type", "unknown"))
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

    discipline_identifier = discipline_id(table["id"], row_index)
    loads: list[dict[str, Any]] = []
    control_assignments = _control_assignments(table, cells, schema, words)
    for semester, span in _semester_spans(schema):
        field_payloads: dict[str, dict[str, Any]] = {}
        for offset, field in enumerate(SEMESTER_FIELD_NAMES):
            start = span[0] + (span[1] - span[0]) * offset / 5
            end = span[0] + (span[1] - span[0]) * (offset + 1) / 5
            field_payloads[field] = _band_payload(cells, words, table, [start, end])
        raw_bands = {field: field_payloads[field]["text"] for field in SEMESTER_FIELD_NAMES}
        raw = {
            field: _strip_control_tokens(raw_bands[field])
            if field != "control"
            else raw_bands[field]
            for field in SEMESTER_FIELD_NAMES
        }
        assigned_controls = control_assignments.get(semester, [])
        assigned_tokens = _unique_tokens(item["token"] for item in assigned_controls)
        control_residual = _strip_control_tokens(raw_bands["control"])
        if words:
            raw["control"] = _clean(" ".join(value for value in [control_residual, *assigned_tokens] if value))
        normalization_notes = [
            f"control_token_removed_from_{field}"
            for field in SEMESTER_FIELD_NAMES[:-1]
            if raw_bands[field] != raw[field]
        ]
        band_control_tokens = _unique_tokens(_control_tokens(raw_bands["control"]))
        numeric_band_control_tokens = _unique_tokens(
            token
            for field in SEMESTER_FIELD_NAMES[:-1]
            for token in _control_tokens(raw_bands[field])
        )
        if assigned_tokens and (
            {token.casefold() for token in band_control_tokens} != {token.casefold() for token in assigned_tokens}
            or numeric_band_control_tokens
            or any(
                item.get("word_id") not in field_payloads["control"]["word_ids"]
                for item in assigned_controls
            )
        ):
            normalization_notes.append("control_reassigned_by_word_start")
        control_tokens = _control_tokens(raw["control"])
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
            "weeks": schema.get("semester_headers", {}).get(str(semester), schema.get("semester_headers", {}).get(semester, {})).get("weeks"),
            "active": any(raw.values()),
            "has_numeric_load": any(_number(raw[field]) is not None for field in SEMESTER_FIELD_NAMES[:-1]),
            "credits": _number(raw["credits"]),
            "hours": _number(raw["hours"]),
            "audited_hours": _number(raw["audited_hours"]),
            "independent_or_other_hours": _number(raw["independent_or_other_hours"]),
            "control": raw["control"],
            "control_tokens": control_tokens,
            "control_kinds": _control_kinds(control_tokens),
            "raw": raw,
            "raw_bands": raw_bands,
            "normalization_notes": normalization_notes,
            "source_cell_ids": sorted({cell_id for payload in field_payloads.values() for cell_id in payload["cell_ids"]}),
            "source_word_ids": sorted(
                {
                    word_id
                    for payload in field_payloads.values()
                    for word_id in payload["word_ids"]
                }
                | {item["word_id"] for item in assigned_controls if item.get("word_id")}
            ),
        }
        if any(len(_number_tokens(raw[field])) > 1 for field in SEMESTER_FIELD_NAMES[:-1]):
            row_record["extraction_warnings"].append(f"В семестре {semester} объединены числовые значения")
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


def extract_semantics(data_dir: Path) -> dict[str, Any]:
    tables = _read_jsonl(data_dir / "study_plan_tables.jsonl")
    table_by_id = {table["id"]: table for table in tables}
    curriculum_tables = [table for table in tables if table.get("section") == "curriculum"]
    cells_path = data_dir / "study_plan_cells.csv"
    schemas_by_document = _discover_schemas(tables, cells_path)
    page_words = _page_words_by_key(data_dir)
    curriculum_ids = {table["id"] for table in curriculum_tables}
    rows: list[dict[str, Any]] = []
    disciplines: list[dict[str, Any]] = []
    loads: list[dict[str, Any]] = []
    processed_tables: set[str] = set()
    state_by_document: dict[str, dict[str, Any]] = defaultdict(lambda: {"section_path": [], "part_type": "unknown"})
    for table_identifier, table_rows in _iter_curriculum_table_rows(cells_path, curriculum_ids):
        table = table_by_id[table_identifier]
        processed_tables.add(table_identifier)
        schema = schemas_by_document.get(table.get("document_id", ""))
        words = page_words.get((table.get("document_id", ""), int(table.get("page_number") or 0)), {})
        state = state_by_document[table.get("document_id", "")]
        for row_index in sorted(table_rows):
            row_record, discipline, row_loads = _semantic_row(table, row_index, table_rows[row_index], schema, words, state)
            rows.append(row_record)
            if discipline is not None:
                disciplines.append(discipline)
                loads.extend(row_loads)

    unresolved_tables = sorted(set(curriculum_ids) - processed_tables)
    tables_without_schema = sorted(
        table["id"] for table in curriculum_tables if table.get("document_id", "") not in schemas_by_document
    )
    missing_subject_fields = [
        item["id"]
        for item in disciplines
        if not item.get("code") or not item.get("name")
    ]
    load_ids = [item["id"] for item in loads]
    reconciliation = _reconcile_totals(disciplines, loads)
    numeric_control_leaks: list[dict[str, Any]] = []
    unclassified_controls: list[dict[str, Any]] = []
    active_without_numeric_or_control: list[dict[str, Any]] = []
    for load in loads:
        for field in SEMESTER_FIELD_NAMES[:-1]:
            tokens = _control_tokens(load.get("raw", {}).get(field, ""))
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
        control = _clean(load.get("control", ""))
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
            1 for item in disciplines if item.get("workload", {}).get("audited_hours") is None
        ),
        "disciplines_without_department": sum(1 for item in disciplines if not item.get("department")),
        "disciplines_with_unknown_part_type": sum(1 for item in disciplines if item.get("part_type") == "unknown"),
        "unallocated_total_without_semester_rows": reconciliation["unallocated_total_without_semester_rows"],
    }
    checks = {
        "all_curriculum_tables_read": not unresolved_tables,
        "all_curriculum_documents_have_schema": not tables_without_schema,
        "discipline_ids_unique": len({item["id"] for item in disciplines}) == len(disciplines),
        "discipline_subject_fields_present": not missing_subject_fields,
        "semester_loads_reference_disciplines": all(item["discipline_id"] in {discipline["id"] for discipline in disciplines} for item in loads),
        "semester_load_ids_unique": len(load_ids) == len(set(load_ids)),
        "all_semantic_rows_reference_cells": all(bool(item.get("source_cell_ids")) for item in rows),
        "allocated_semester_totals_reconcile": reconciliation["active_semester_mismatches"] == 0,
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
            "numeric_semester_loads": sum(1 for item in loads if item["has_numeric_load"]),
            "controls": sum(1 for item in loads if item["control"]),
        },
        "reconciliation": reconciliation,
        "schemas": {
            "documents": len(schemas_by_document),
            "semester_counts": dict(Counter(schema["semester_count"] for schema in schemas_by_document.values())),
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
    return {
        "schemas": list(schemas_by_document.values()),
        "curriculum_rows": rows,
        "disciplines": disciplines,
        "semester_loads": loads,
        "resolution": resolution,
        "report": report,
    }


def _csv_semantic_rows(loads: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        item["control_tokens"] = json.dumps(item.get("control_tokens", []), ensure_ascii=False, separators=(",", ":"))
        item["control_kinds"] = json.dumps(item.get("control_kinds", []), ensure_ascii=False, separators=(",", ":"))
        item["raw"] = json.dumps(item.get("raw", {}), ensure_ascii=False, separators=(",", ":"))
        item["raw_bands"] = json.dumps(item.get("raw_bands", {}), ensure_ascii=False, separators=(",", ":"))
        item["normalization_notes"] = json.dumps(item.get("normalization_notes", []), ensure_ascii=False, separators=(",", ":"))
        item["source_cell_ids"] = json.dumps(item.get("source_cell_ids", []), ensure_ascii=False, separators=(",", ":"))
        item["source_word_ids"] = json.dumps(item.get("source_word_ids", []), ensure_ascii=False, separators=(",", ":"))
        output.append({field: item.get(field, "") for field in fields})
    return output


def write_semantic_dataset(data_dir: Path, semantic: dict[str, Any]) -> None:
    write_jsonl(data_dir / "study_plan_curriculum_rows.jsonl", semantic["curriculum_rows"])
    write_jsonl(data_dir / "study_plan_disciplines.jsonl", semantic["disciplines"])
    write_jsonl(data_dir / "study_plan_discipline_entities.jsonl", semantic["resolution"]["entities"])
    write_csv(
        data_dir / "study_plan_semester_load.csv",
        _csv_semantic_rows(semantic["semester_loads"]),
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
    write_json(data_dir / "study_plan_curriculum_schema.json", {"schema_version": "1.0", "documents": semantic["schemas"]})
    write_json(data_dir / "study_plan_resolution_report.json", semantic["resolution"])
    write_json(data_dir / "study_plan_semantic_report.json", semantic["report"])


def extend_ontology_with_semantics(data_dir: Path, semantic: dict[str, Any]) -> dict[str, Any]:
    ontology_path = data_dir / "study_plan_ontology.json"
    ontology = json.loads(ontology_path.read_text(encoding="utf-8")) if ontology_path.exists() else {"schema_version": "2.0", "objects": {}, "links": []}
    object_buckets: dict[str, dict[str, dict[str, Any]]] = {
        object_type: {item["id"]: item for item in values}
        for object_type, values in ontology.get("objects", {}).items()
    }
    links = {item["id"]: item for item in ontology.get("links", [])}
    documents = {item["document_id"]: item for item in _read_jsonl(data_dir / "study_plan_documents.jsonl")}
    row_object_ids = {
        item["id"]
        for item in object_buckets.get("study_plan_row", {}).values()
    }

    def provenance(document_id: str, dataset: str) -> dict[str, Any]:
        document = documents.get(document_id, {})
        return {
            "source_url": document.get("source_url", ""),
            "resolved_url": document.get("resolved_url", ""),
            "local_path": document.get("local_path", ""),
            "raw_dataset": dataset,
            "extracted_at_utc": document.get("extracted_at_utc", ""),
        }

    def add_object(object_type: str, identifier: str, properties: dict[str, Any], source: dict[str, Any]) -> None:
        bucket = object_buckets.setdefault(object_type, {})
        bucket[identifier] = {
            "id": identifier,
            "object_type": object_type,
            "properties": properties,
            "provenance": source,
        }

    def add_link(link_type: str, from_id: str, to_id: str, source: dict[str, Any]) -> None:
        identifier = link_id(link_type, from_id, to_id)
        links.setdefault(
            identifier,
            {
                "id": identifier,
                "link_type": link_type,
                "from_id": from_id,
                "to_id": to_id,
                "properties": {},
                "provenance": source,
            },
        )

    for discipline in semantic["disciplines"]:
        source = provenance(discipline["document_id"], "study_plan_disciplines.jsonl")
        add_object(
            "study_plan_discipline",
            discipline["id"],
            {
                "source_key": discipline["id"],
                "code": discipline["code"],
                "name": discipline["name"],
                "department": discipline["department"],
                "part_type": discipline["part_type"],
                "section_path": discipline["section_path"],
                "workload": discipline["workload"],
                "class_hours": discipline["class_hours"],
                "semester_count": discipline["semester_count"],
                "source_row_id": discipline["source_row_id"],
                "source_cells_dataset": discipline["source_cells_dataset"],
            },
            source,
        )
        document_id = discipline["document_id"]
        if document_id in object_buckets.get("study_plan_document", {}):
            add_link("study_plan_document_has_discipline", document_id, discipline["id"], source)
        if discipline["source_row_id"] in row_object_ids:
            add_link("study_plan_row_is_discipline", discipline["source_row_id"], discipline["id"], source)

    for load in semantic["semester_loads"]:
        source = provenance(load["document_id"], "study_plan_semester_load.csv")
        add_object(
            "study_plan_semester_load",
            load["id"],
            {
                "source_key": load["id"],
                "discipline_id": load["discipline_id"],
                "semester": load["semester"],
                "weeks": load["weeks"],
                "active": load["active"],
                "has_numeric_load": load["has_numeric_load"],
                "credits": load["credits"],
                "hours": load["hours"],
                "audited_hours": load["audited_hours"],
                "independent_or_other_hours": load["independent_or_other_hours"],
                "control": load["control"],
                "control_tokens": load["control_tokens"],
                "control_kinds": load["control_kinds"],
                "raw_bands": load["raw_bands"],
                "normalization_notes": load["normalization_notes"],
                "source_row_id": load["source_row_id"],
                "source_cells_dataset": "study_plan_cells.csv",
            },
            source,
        )
        add_link("study_plan_discipline_has_semester_load", load["discipline_id"], load["id"], source)

    for entity in semantic.get("resolution", {}).get("entities", []):
        source_discipline_ids = entity.get("source_discipline_ids", [])
        source_document_id = next(
            (
                discipline.get("document_id", "")
                for discipline in semantic["disciplines"]
                if discipline.get("id") == (source_discipline_ids[0] if source_discipline_ids else "")
            ),
            "",
        )
        source = provenance(source_document_id, "study_plan_discipline_entities.jsonl")
        add_object(
            "study_plan_discipline_entity",
            entity["id"],
            {
                "source_key": entity["id"],
                "resolution_key": entity["resolution_key"],
                "status": entity["status"],
                "code": entity["code"],
                "name": entity["name"],
                "aliases": entity["aliases"],
                "source_discipline_ids": source_discipline_ids,
                "source_documents": entity["source_documents"],
                "conflicts": entity["conflicts"],
            },
            source,
        )
        for source_discipline_id in source_discipline_ids:
            if source_discipline_id in object_buckets.get("study_plan_discipline", {}):
                add_link(
                    "study_plan_discipline_resolves_to_entity",
                    source_discipline_id,
                    entity["id"],
                    source,
                )

    ontology["schema_version"] = "3.1"
    ontology["objects"] = {
        object_type: [bucket[key] for key in sorted(bucket)]
        for object_type, bucket in sorted(object_buckets.items())
    }
    ontology["links"] = [links[key] for key in sorted(links)]
    write_json(ontology_path, ontology)
    return ontology


def enrich_existing_dataset(result_dir: Path) -> dict[str, Any]:
    data_dir = result_dir / "study_plan_data"
    if not (data_dir / "study_plan_cells.csv").exists():
        raise FileNotFoundError(f"Не найден полный набор ячеек: {data_dir / 'study_plan_cells.csv'}")
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
                "objects": sum(len(bucket) for bucket in ontology.get("objects", {}).values()),
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
        run.finish(status="succeeded" if report["verification"]["passed"] else "failed", quality=report)
        return report
    except Exception as exc:
        run.finish(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
