from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    result_dir: str
    dataset_ready: bool
    quality_passed: bool | None = None
    data_engine: Literal["duckdb", "file"] = "duckdb"


class DatasetDescriptor(BaseModel):
    name: str
    format: Literal["csv", "jsonl"]
    path: str
    description: str
    available: bool
    size_bytes: int | None = None


class DatasetCatalogResponse(BaseModel):
    datasets: list[DatasetDescriptor]


class DatasetPage(BaseModel):
    dataset: str
    items: list[dict[str, Any]]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    total: int = Field(ge=0)
    has_more: bool


OperationName = Literal[
    "refresh",
    "extract_study_plans",
    "extract_semantics",
    "compact_study_plans",
]


class OperationRequest(BaseModel):
    operation: OperationName = Field(description="Операция над данными")
    workers: int = Field(
        default=4, ge=1, le=32, description="Число параллельных workers"
    )
    strict: bool = Field(
        default=True, description="Считать операцию неуспешной при провале quality gate"
    )
    download_plans: bool = Field(
        default=False, description="Для refresh: скачивать учебные планы"
    )
    resolve_plans: bool = Field(
        default=True, description="Для refresh: разрешать ссылки учебных планов"
    )
    reader_backend: Literal["native", "docling"] = Field(
        default="native", description="Backend извлечения PDF/DOCX"
    )
    resume: bool = Field(
        default=True,
        description="Возобновлять извлечение по неповреждённым checkpoints",
    )
    page_size: int = Field(
        default=100, ge=1, le=500, description="Для refresh: размер страницы API"
    )
    timeout: float = Field(
        default=30.0, gt=0, le=300, description="Для refresh: HTTP timeout"
    )
    delay: float = Field(
        default=0.15, ge=0, le=60, description="Для refresh: пауза между запросами"
    )


class OperationStatus(BaseModel):
    id: str
    operation: str
    status: Literal["queued", "running", "succeeded", "failed"]
    submitted_at_utc: str
    started_at_utc: str | None = None
    finished_at_utc: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
