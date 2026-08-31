from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol
from pathlib import Path

from ..domain.ids import stable_id


ReaderResult = tuple[list[dict[str, Any]], list[dict[str, Any]], str, list[str]]


class DocumentReader(Protocol):
    name: str

    def extract(self, path: Path, document_id: str) -> ReaderResult: ...


class NativeDocumentReader:
    """Adapter over the project's existing Poppler/pdfplumber/docx reader."""

    name = "native"

    def extract(self, path: Path, document_id: str) -> ReaderResult:
        # Lazy import keeps the reader seam free of a circular dependency.
        from .reader import _extract_docx, _extract_pdf

        if path.suffix.casefold() == ".pdf":
            return _extract_pdf(path, document_id)
        if path.suffix.casefold() == ".docx":
            return _extract_docx(path, document_id)
        raise RuntimeError(f"Ожидался PDF/DOCX, получен файл {path.name}")


def _docling_bbox(value: dict[str, Any]) -> tuple[dict[str, float] | None, int | None]:
    provenance = value.get("prov")
    entries = provenance if isinstance(provenance, list) else []
    for item in entries:
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else item
        if not isinstance(bbox, dict):
            continue
        if all(key in bbox for key in ("l", "t", "r", "b")):
            return (
                {
                    "x0": float(bbox["l"]),
                    "top": float(bbox["t"]),
                    "x1": float(bbox["r"]),
                    "bottom": float(bbox["b"]),
                },
                _int_or_none(item.get("page_no")),
            )
        if all(key in bbox for key in ("x0", "top", "x1", "bottom")):
            return (
                {key: float(bbox[key]) for key in ("x0", "top", "x1", "bottom")},
                _int_or_none(item.get("page_no")),
            )
    return None, None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _table_section(column_count: int, bbox: dict[str, float] | None) -> str:
    if column_count >= 60:
        return "curriculum"
    if column_count >= 25:
        return "calendar_schedule"
    if bbox and bbox.get("x0", 0) >= 700:
        return "time_budget_summary"
    if column_count <= 10:
        return "time_budget_summary"
    return "other"


def _docling_text(data: dict[str, Any]) -> str:
    values: list[str] = []
    for collection in ("texts", "titles", "groups"):
        for item in (
            data.get(collection, []) if isinstance(data.get(collection), list) else []
        ):
            if isinstance(item, dict) and str(item.get("text", "")).strip():
                values.append(str(item["text"]).strip())
    return "\n".join(values)


class DoclingDocumentReader:
    """Optional Docling adapter mapped back to BMSTU's cell-level contract.

    Docling is intentionally not the semantic authority. Its structured
    document is converted into our pages/tables/rows/cells shape; current
    coordinate-based semantic rules and quality gates then decide what is
    acceptable. Word anchors are absent when Docling does not expose them, so
    the result carries an explicit warning instead of inventing anchors.
    """

    name = "docling"

    def __init__(self, converter_factory: Callable[[], Any] | None = None) -> None:
        self._converter_factory = converter_factory

    def _converter(self) -> Any:
        if self._converter_factory is not None:
            return self._converter_factory()
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Для reader_backend=docling установите optional dependency: pip install -e .[docling]"
            ) from exc
        return DocumentConverter()

    def extract(self, path: Path, document_id: str) -> ReaderResult:
        result = self._converter().convert(path)
        document = getattr(result, "document", result)
        data = (
            document.export_to_dict()
            if hasattr(document, "export_to_dict")
            else document
        )
        if not isinstance(data, dict):
            raise RuntimeError("Docling вернул неподдерживаемую структуру документа")

        pages_data = data.get("pages") if isinstance(data.get("pages"), dict) else {}
        page_numbers: set[int] = set()
        pages: dict[int, dict[str, Any]] = {}
        for raw_number, page_data in pages_data.items():
            number = _int_or_none(raw_number) or 1
            page_numbers.add(number)
            size = page_data.get("size", {}) if isinstance(page_data, dict) else {}
            pages[number] = {
                "page_number": number,
                "width": size.get("width") if isinstance(size, dict) else None,
                "height": size.get("height") if isinstance(size, dict) else None,
                "words": [],
                "lines": [],
                "table_ids": [],
            }

        tables: list[dict[str, Any]] = []
        raw_tables = data.get("tables") if isinstance(data.get("tables"), list) else []
        for table_index, table in enumerate(raw_tables):
            if not isinstance(table, dict):
                continue
            bbox, page_number = _docling_bbox(table)
            page_number = page_number or 1
            page_numbers.add(page_number)
            table_id = stable_id(
                "study-plan-table", document_id, page_number, table_index
            )
            table_data = (
                table.get("data") if isinstance(table.get("data"), dict) else {}
            )
            grid = (
                table_data.get("grid")
                if isinstance(table_data.get("grid"), list)
                else []
            )
            if not grid:
                cells = (
                    table_data.get("table_cells")
                    if isinstance(table_data.get("table_cells"), list)
                    else []
                )
                rows_by_index: dict[int, list[dict[str, Any]]] = {}
                for cell in cells:
                    if not isinstance(cell, dict):
                        continue
                    row = _int_or_none(cell.get("start_row_offset_idx")) or 0
                    col = _int_or_none(cell.get("start_col_offset_idx")) or 0
                    while len(rows_by_index.setdefault(row, [])) <= col:
                        rows_by_index[row].append({})
                    rows_by_index[row][col] = cell
                grid = [rows_by_index[index] for index in sorted(rows_by_index)]

            rows: list[list[dict[str, Any]]] = []
            for row_index, row in enumerate(grid):
                if not isinstance(row, list):
                    continue
                cell_row: list[dict[str, Any]] = []
                for column_index, raw_cell in enumerate(row):
                    if raw_cell is None:
                        cell_row.append(
                            {
                                "id": stable_id(
                                    "study-plan-cell", table_id, row_index, column_index
                                ),
                                "table_id": table_id,
                                "row_index": row_index,
                                "column_index": column_index,
                                "text": "",
                                "bbox": None,
                                "word_ids": [],
                                "cell_kind": "merged_placeholder",
                            }
                        )
                        continue
                    cell = (
                        raw_cell
                        if isinstance(raw_cell, dict)
                        else {"text": str(raw_cell)}
                    )
                    cell_bbox, _ = _docling_bbox(cell)
                    cell_row.append(
                        {
                            "id": stable_id(
                                "study-plan-cell", table_id, row_index, column_index
                            ),
                            "table_id": table_id,
                            "row_index": row_index,
                            "column_index": column_index,
                            "text": str(cell.get("text", "")),
                            "bbox": cell_bbox,
                            "word_ids": [],
                            "cell_kind": "docling_header_cell"
                            if cell.get("column_header")
                            else "docling_cell",
                        }
                    )
                rows.append(cell_row)

            record = {
                "id": table_id,
                "document_id": document_id,
                "page_number": page_number,
                "table_index": table_index,
                "section": _table_section(
                    max((len(row) for row in rows), default=0), bbox
                ),
                "bbox": bbox,
                "row_count": len(rows),
                "column_count": max((len(row) for row in rows), default=0),
                "rows": rows,
                "extraction_method": "docling",
            }
            tables.append(record)
            pages.setdefault(
                page_number,
                {
                    "page_number": page_number,
                    "width": None,
                    "height": None,
                    "words": [],
                    "lines": [],
                    "table_ids": [],
                },
            )["table_ids"].append(table_id)

        page_records = [pages[number] for number in sorted(page_numbers or {1})]
        warnings = [
            "Docling не предоставляет word-level anchors; семантическая привязка использует cell fallback"
        ]
        if not tables:
            warnings.append("Docling не обнаружил таблицы")
        layout_text = (
            document.export_to_markdown()
            if hasattr(document, "export_to_markdown")
            else _docling_text(data)
        )
        return page_records, tables, str(layout_text), warnings


def get_reader_backend(backend: str | DocumentReader) -> DocumentReader:
    if hasattr(backend, "extract"):
        return backend
    normalized = str(backend).casefold()
    if normalized == "native":
        return NativeDocumentReader()
    if normalized == "docling":
        return DoclingDocumentReader()
    raise ValueError(f"Неподдерживаемый reader backend: {backend}")
