from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .semantic_shared import clean, json_value, read_jsonl


def bbox(value: Any) -> dict[str, float] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json_value(value, None)
        return parsed if isinstance(parsed, dict) else None
    return None


def cell_from_csv(row: dict[str, str]) -> dict[str, Any]:
    return {
        "id": row.get("id", ""),
        "column_index": int(row.get("column_index") or 0),
        "row_index": int(row.get("row_index") or 0),
        "text": row.get("text", ""),
        "bbox": bbox(row.get("bbox", "")),
        "word_ids": json_value(row.get("word_ids", ""), []),
    }


def table_bounds(
    table: dict[str, Any], rows: dict[int, list[dict[str, Any]]]
) -> tuple[float, float]:
    table_bbox = bbox(table.get("bbox")) or {}
    x0 = table_bbox.get("x0")
    x1 = table_bbox.get("x1")
    if x0 is not None and x1 is not None and x1 > x0:
        return float(x0), float(x1)
    boxes = [
        cell["bbox"]
        for row in rows.values()
        for cell in row
        if cell.get("bbox")
        and cell["bbox"].get("x0") is not None
        and cell["bbox"].get("x1") is not None
    ]
    if not boxes:
        return 0.0, 1.0
    return min(float(box["x0"]) for box in boxes), max(
        float(box["x1"]) for box in boxes
    )


def normalized_span(
    box: dict[str, float] | None, x0: float, width: float
) -> list[float] | None:
    if not box or width <= 0:
        return None
    left = max(0.0, min(1.0, (float(box["x0"]) - x0) / width))
    right = max(left, min(1.0, (float(box["x1"]) - x0) / width))
    return [left, right]


def find_header_span(
    cells: Iterable[dict[str, Any]],
    predicate: Any,
    x0: float,
    width: float,
) -> list[float] | None:
    candidates = [
        cell
        for cell in cells
        if predicate(clean(cell.get("text", "")).lower()) and cell.get("bbox")
    ]
    if not candidates:
        return None
    candidate = min(candidates, key=lambda cell: float(cell["bbox"]["x0"]))
    return normalized_span(candidate["bbox"], x0, width)


def join_words(words: list[dict[str, Any]]) -> str:
    if not words:
        return ""
    ordered = sorted(
        words, key=lambda word: (float(word.get("top", 0)), float(word.get("x0", 0)))
    )
    lines: list[list[dict[str, Any]]] = []
    for word in ordered:
        if (
            not lines
            or abs(float(word.get("top", 0)) - float(lines[-1][0].get("top", 0))) > 1.6
        ):
            lines.append([word])
        else:
            lines[-1].append(word)
    return "\n".join(
        " ".join(str(word.get("text", "")) for word in line) for line in lines
    ).strip()


def row_words(
    cells: list[dict[str, Any]], page_words: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    identifiers = {word_id for cell in cells for word_id in cell.get("word_ids", [])}
    return sorted(
        (page_words[word_id] for word_id in identifiers if word_id in page_words),
        key=lambda word: (
            float(word.get("top", 0)),
            float(word.get("x0", 0)),
            str(word.get("id", "")),
        ),
    )


def overlap(left: float, right: float, other_left: float, other_right: float) -> bool:
    return min(right, other_right) - max(left, other_left) > 0.1


def band_payload(
    cells: list[dict[str, Any]],
    words: list[dict[str, Any]],
    table: dict[str, Any],
    span: list[float],
) -> dict[str, Any]:
    table_x0, table_x1 = table_bounds(table, {0: cells})
    width = max(table_x1 - table_x0, 1.0)
    left = table_x0 + span[0] * width
    right = table_x0 + span[1] * width
    selected_words = [
        word
        for word in words
        if left - 0.15
        <= (float(word.get("x0", 0)) + float(word.get("x1", 0))) / 2
        <= right + 0.15
    ]
    source_cells = [
        cell["id"]
        for cell in cells
        if cell.get("bbox")
        and overlap(left, right, float(cell["bbox"]["x0"]), float(cell["bbox"]["x1"]))
    ]
    text = join_words(selected_words)
    # Word coordinates are authoritative. Cell text is a fallback for readers
    # that cannot provide word-level anchors (for example Docling tables).
    if not text and not words:
        fallback = [
            cell.get("text", "")
            for cell in cells
            if cell.get("bbox")
            and left - 0.15
            <= (float(cell["bbox"]["x0"]) + float(cell["bbox"]["x1"])) / 2
            <= right + 0.15
            and clean(cell.get("text", ""))
        ]
        text = " ".join(fallback)
    return {
        "text": clean(text),
        "cell_ids": sorted(set(source_cells)),
        "word_ids": sorted(
            {str(word.get("id", "")) for word in selected_words if word.get("id")}
        ),
    }


def page_words_by_key(
    data_dir: Path,
) -> dict[tuple[str, int], dict[str, dict[str, Any]]]:
    pages: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for page in read_jsonl(data_dir / "study_plan_pages.jsonl"):
        key = (page.get("document_id", ""), int(page.get("page_number") or 0))
        pages[key] = {
            str(word.get("id")): word
            for word in page.get("words", [])
            if word.get("id")
        }
    return pages


def semester_spans(schema: dict[str, Any]) -> list[tuple[int, list[float]]]:
    start = float(schema["semester_start_rel"])
    end = float(schema["semester_end_rel"])
    count = int(schema["semester_count"])
    width = (end - start) / max(count, 1)
    return [
        (semester, [start + (semester - 1) * width, start + semester * width])
        for semester in range(1, count + 1)
    ]


def control_assignments(
    table: dict[str, Any],
    cells: list[dict[str, Any]],
    schema: dict[str, Any],
    words: list[dict[str, Any]],
    semester_field_count: int,
    control_tokens: Any,
) -> dict[int, list[dict[str, str]]]:
    """Assign control words to semester bands by their left edge."""

    if not words:
        return {}
    table_x0, table_x1 = table_bounds(table, {0: cells})
    table_width = max(table_x1 - table_x0, 1.0)
    semester_start = table_x0 + float(schema["semester_start_rel"]) * table_width
    control_bands: list[tuple[int, float, float]] = []
    for semester, span in semester_spans(schema):
        left = table_x0 + span[0] * table_width
        right = table_x0 + span[1] * table_width
        field_width = (right - left) / semester_field_count
        control_bands.append(
            (semester, left + field_width * (semester_field_count - 1), right)
        )

    assignments: dict[int, list[dict[str, str]]] = defaultdict(list)
    for word in words:
        anchor = float(word.get("x0", 0))
        if anchor < semester_start - 1.0:
            continue
        tokens = control_tokens(str(word.get("text", "")))
        if not tokens:
            continue

        def distance(item: tuple[int, float, float], anchor: float = anchor) -> float:
            _semester, left, right = item
            if left <= anchor <= right:
                return 0.0
            return min(abs(anchor - left), abs(anchor - right))

        semester = min(control_bands, key=distance)[0]
        for token in tokens:
            assignments[semester].append(
                {"token": token, "word_id": str(word.get("id", ""))}
            )
    return assignments
