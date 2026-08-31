from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class UniversityDescriptor(BaseModel):
    university_id: str
    display_name: str
    capabilities: dict[str, bool]
    capability_status: dict[str, str]
    data_ready: bool


class DatasetDescriptor(BaseModel):
    name: str
    format: Literal["csv", "jsonl"]
    path: str
    description: str
    available: bool
    size_bytes: int | None = None


class DatasetPage(BaseModel):
    dataset: str
    items: list[dict[str, Any]]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    total: int = Field(ge=0)
    has_more: bool


OperationName = Literal[
    "refresh", "extract_study_plans", "extract_semantics", "compact_study_plans"
]


class OperationRequest(BaseModel):
    operation: OperationName
    workers: int = Field(default=4, ge=1, le=32)
    strict: bool = True
    download_plans: bool = False
    resolve_plans: bool = True
    reader_backend: Literal["native", "docling"] = "native"
    resume: bool = True
    page_size: int = Field(default=100, ge=1, le=500)
    timeout: float = Field(default=30.0, gt=0, le=300)
    delay: float = Field(default=0.15, ge=0, le=60)


class OperationStatus(BaseModel):
    id: str
    university_id: str
    operation: str
    status: Literal["queued", "running", "succeeded", "failed"]
    submitted_at_utc: str
    started_at_utc: str | None = None
    finished_at_utc: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
