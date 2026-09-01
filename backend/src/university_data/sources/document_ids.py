from __future__ import annotations

from ..domain.ids import global_stable_id


def stable_id(kind: str, *parts: object) -> str:
    return global_stable_id("platform", kind, *parts)


def table_id(document_id: str, page_number: int, table_index: int) -> str:
    return stable_id("study-plan-table", document_id, page_number, table_index)


def row_id(table_identifier: str, row_index: int) -> str:
    return stable_id("study-plan-row", table_identifier, row_index)


def discipline_id(
    table_identifier: str,
    code: str,
    name: str,
    department: str = "",
    section_path: tuple[str, ...] | list[str] = (),
) -> str:
    """Build a discipline ID from business fields, never a row position."""

    return stable_id(
        "study-plan-discipline",
        table_identifier,
        code or name,
        name,
        department,
        "|".join(section_path),
    )


def semester_load_id(discipline_identifier: str, semester: int) -> str:
    return stable_id("study-plan-semester-load", discipline_identifier, semester)
