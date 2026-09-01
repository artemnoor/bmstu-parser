from __future__ import annotations

from ..domain.ids import stable_id


def table_id(document_id: str, page_number: int, table_index: int) -> str:
    return stable_id("study-plan-table", document_id, page_number, table_index)


def row_id(table_identifier: str, row_index: int) -> str:
    return stable_id("study-plan-row", table_identifier, row_index)


def discipline_id(
    table_identifier: str,
    code: str,
    name: str,
    department: str = "",
    part_type: str = "",
    section_path: tuple[str, ...] | list[str] = (),
) -> str:
    """Return a discipline ID from semantic business identity.

    ``row_index`` remains a physical locator for audit data, but is no longer
    used to identify the discipline itself.  A true duplicate is handled by
    the caller with an explicit duplicate ordinal.
    """

    return stable_id(
        "study-plan-discipline",
        table_identifier,
        code or name,
        name,
        department,
        part_type,
        "|".join(section_path),
    )


def semester_load_id(discipline_identifier: str, semester: int) -> str:
    return stable_id("study-plan-semester-load", discipline_identifier, semester)
