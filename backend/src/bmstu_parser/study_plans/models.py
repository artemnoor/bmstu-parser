from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class StudyPlanReference:
    document_id: str
    local_path: str
    major_id: str
    major_slug: str
    major_code: str
    major_name: str
    program_id: str
    program_code: str
    program_name: str
    plan_url: str
    plan_status: str
    source_url: str
    resolved_url: str
    expected_size: int | None = None
    expected_sha256: str = ""
    expected_mime_type: str = ""


@dataclass(slots=True)
class ExtractedDocument:
    document_id: str
    local_path: str
    absolute_path: str
    kind: str
    status: str
    source_references: list[dict[str, Any]]
    source_url: str
    resolved_url: str
    source_size: int
    source_sha256: str
    expected_size: int | None
    expected_sha256: str
    expected_mime_type: str
    page_count: int = 0
    paragraph_count: int = 0
    table_count: int = 0
    row_count: int = 0
    cell_count: int = 0
    raw_layout_path: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    extraction_backend: str = "native"
    extracted_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
