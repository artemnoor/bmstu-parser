from __future__ import annotations

from ..domain.ids import stable_id


def table_id(document_id: str, page_number: int, table_index: int) -> str:
    return stable_id("study-plan-table", document_id, page_number, table_index)


def row_id(table_identifier: str, row_index: int) -> str:
    return stable_id("study-plan-row", table_identifier, row_index)


def discipline_id(table_identifier: str, row_index: int) -> str:
    return stable_id("study-plan-discipline", table_identifier, row_index)


def semester_load_id(discipline_identifier: str, semester: int) -> str:
    return stable_id("study-plan-semester-load", discipline_identifier, semester)
