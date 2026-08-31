from __future__ import annotations

import hmac
import re
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .. import __version__
from .config import ApiSettings
from .job_store import SqliteJobStore
from .jobs import JobManager, OperationConflictError
from .models import (
    DatasetCatalogResponse,
    DatasetPage,
    HealthResponse,
    OperationRequest,
    OperationStatus,
)
from .operations import execute_operation
from .repository import DatasetNotFoundError, DatasetRepository, DatasetUnavailableError

SERVICE_NAME = "bmstu-education-api"


def create_app(
    settings: ApiSettings | None = None,
    *,
    operation_executor: Callable[
        [OperationRequest, Any], dict[str, Any]
    ] = execute_operation,
    job_manager: JobManager | None = None,
) -> FastAPI:
    api_settings = settings or ApiSettings.from_env()
    if api_settings.is_production and not api_settings.api_key:
        raise RuntimeError("BMSTU_API_KEY обязателен при BMSTU_ENV=production")
    repository = DatasetRepository(
        api_settings.result_dir, engine=api_settings.dataset_engine
    )
    jobs = job_manager or JobManager(
        store=SqliteJobStore(
            api_settings.result_dir / "pipeline_runs" / "operations.sqlite3",
            max_records=api_settings.operation_max_records,
            ttl_seconds=api_settings.operation_ttl_seconds,
        )
    )
    owns_jobs = job_manager is None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        if owns_jobs:
            jobs.shutdown()

    app = FastAPI(
        title="BMSTU Education Data API",
        summary="API для взаимодействия с каноническими данными программ и учебных планов МГТУ им. Н. Э. Баумана",
        description=(
            "REST API поверх raw, canonical и semantic datasets BMSTU parser. "
            "Swagger UI доступен по `/docs`, ReDoc — по `/redoc`, OpenAPI-контракт — по `/openapi.json`. "
            "Записи выдаются постранично, а все изменения выполняются как наблюдаемые фоновые операции."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = api_settings
    app.state.repository = repository
    app.state.jobs = jobs

    @app.middleware("http")
    async def security_headers(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        request_id = request.headers.get("X-Request-ID", "")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request_id):
            request_id = uuid4().hex
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    if api_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(api_settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-API-Key"],
        )

    def require_write_access(
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> None:
        if api_settings.api_key and not hmac.compare_digest(
            x_api_key or "", api_settings.api_key
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный или отсутствующий X-API-Key",
            )

    def page_dataset(
        dataset_name: str,
        *,
        offset: int,
        limit: int,
        query: str | None,
        row_id: str | None,
        document_id: str | None,
        table_id: str | None,
        discipline_id: str | None,
        major_id: str | None,
        program_id: str | None,
        department_id: str | None,
        slug: str | None,
        code: str | None = None,
    ) -> dict[str, Any]:
        filters = {
            key: value
            for key, value in {
                "id": row_id,
                "document_id": document_id,
                "table_id": table_id,
                "discipline_id": discipline_id,
                "major_id": major_id,
                "program_id": program_id,
                "department_id": department_id,
                "slug": slug,
                "code": code,
            }.items()
            if value
        }
        try:
            return repository.page(
                dataset_name, offset=offset, limit=limit, filters=filters, query=query
            )
        except DatasetNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
        except DatasetUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc

    def first_dataset(
        dataset_name: str, field: str, value: str
    ) -> dict[str, Any] | None:
        try:
            return repository.first(dataset_name, field, value)
        except DatasetNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
        except DatasetUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc

    @app.get("/", tags=["system"], include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "service": SERVICE_NAME,
            "docs": "/docs",
            "redoc": "/redoc",
            "openapi": "/openapi.json",
        }

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        quality_passed = repository.quality_passed()
        data_ready = (api_settings.result_dir / "parse_report.json").exists()
        return HealthResponse(
            status="ok" if data_ready and quality_passed is not False else "degraded",
            service=SERVICE_NAME,
            version=__version__,
            result_dir=str(api_settings.result_dir),
            dataset_ready=data_ready,
            quality_passed=quality_passed,
            data_engine=repository.engine,
        )

    @app.get("/api/v1/catalog", tags=["catalog"])
    def catalog() -> dict[str, Any]:
        return {"datasets": repository.descriptors(), "quality": repository.reports()}

    @app.get("/api/v1/quality", tags=["catalog"])
    def quality() -> dict[str, Any]:
        return repository.reports()

    @app.get("/api/v1/runs", tags=["system"])
    def runs(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        return {"items": repository.runs(limit=limit), "limit": limit}

    @app.get("/api/v1/runs/{run_id}", tags=["system"])
    def run(run_id: str) -> dict[str, Any]:
        item = repository.run(run_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Запуск не найден: {run_id}",
            )
        return item

    @app.get(
        "/api/v1/datasets", response_model=DatasetCatalogResponse, tags=["datasets"]
    )
    def datasets() -> DatasetCatalogResponse:
        return DatasetCatalogResponse(datasets=repository.descriptors())

    @app.get("/api/v1/datasets/{dataset_name}", tags=["datasets"])
    def dataset(dataset_name: str) -> dict[str, Any]:
        try:
            spec = repository.spec(dataset_name)
        except DatasetNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
        path = repository.path_for(dataset_name)
        return {
            "name": spec.name,
            "format": spec.format,
            "path": str(spec.relative_path).replace("\\", "/"),
            "description": spec.description,
            "available": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else None,
        }

    @app.get(
        "/api/v1/datasets/{dataset_name}/rows",
        response_model=DatasetPage,
        tags=["datasets"],
    )
    def dataset_rows(
        dataset_name: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=500),
        q: str | None = Query(
            default=None, description="Полнотекстовый поиск по сериализованной записи"
        ),
        id: str | None = Query(default=None, description="Точное значение поля id"),
        document_id: str | None = None,
        table_id: str | None = None,
        discipline_id: str | None = None,
        major_id: str | None = None,
        program_id: str | None = None,
        department_id: str | None = None,
        slug: str | None = None,
    ) -> DatasetPage:
        return DatasetPage(
            **page_dataset(
                dataset_name,
                offset=offset,
                limit=limit,
                query=q,
                row_id=id,
                document_id=document_id,
                table_id=table_id,
                discipline_id=discipline_id,
                major_id=major_id,
                program_id=program_id,
                department_id=department_id,
                slug=slug,
            )
        )

    @app.get("/api/v1/majors", response_model=DatasetPage, tags=["domain"])
    def majors(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=500),
        q: str | None = None,
        code: str | None = None,
        slug: str | None = None,
    ) -> DatasetPage:
        result = page_dataset(
            "majors",
            offset=offset,
            limit=limit,
            query=q,
            row_id=None,
            document_id=None,
            table_id=None,
            discipline_id=None,
            major_id=None,
            program_id=None,
            department_id=None,
            slug=slug,
            code=code,
        )
        return DatasetPage(**result)

    @app.get("/api/v1/majors/{slug}", tags=["domain"])
    def major(slug: str) -> dict[str, Any]:
        item = first_dataset("majors", "slug", slug)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Направление не найдено: {slug}",
            )
        return item

    @app.get("/api/v1/programs", response_model=DatasetPage, tags=["domain"])
    def programs(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=500),
        q: str | None = None,
        major_id: str | None = None,
        department_id: str | None = None,
    ) -> DatasetPage:
        return DatasetPage(
            **page_dataset(
                "educational_programs",
                offset=offset,
                limit=limit,
                query=q,
                row_id=None,
                document_id=None,
                table_id=None,
                discipline_id=None,
                major_id=major_id,
                program_id=None,
                department_id=department_id,
                slug=None,
            )
        )

    @app.get("/api/v1/programs/{program_id}", tags=["domain"])
    def program(program_id: str) -> dict[str, Any]:
        item = first_dataset("educational_programs", "id", program_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Программа не найдена: {program_id}",
            )
        return item

    @app.get(
        "/api/v1/study-plans/documents",
        response_model=DatasetPage,
        tags=["study plans"],
    )
    def study_plan_documents(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=500),
        q: str | None = None,
        program_id: str | None = None,
    ) -> DatasetPage:
        return DatasetPage(
            **page_dataset(
                "study_plan_documents",
                offset=offset,
                limit=limit,
                query=q,
                row_id=None,
                document_id=None,
                table_id=None,
                discipline_id=None,
                major_id=None,
                program_id=program_id,
                department_id=None,
                slug=None,
            )
        )

    @app.get("/api/v1/study-plans/documents/{document_id}", tags=["study plans"])
    def study_plan_document(document_id: str) -> dict[str, Any]:
        item = first_dataset("study_plan_documents", "document_id", document_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Документ не найден: {document_id}",
            )
        return item

    @app.get(
        "/api/v1/study-plans/documents/{document_id}/tables",
        response_model=DatasetPage,
        tags=["study plans"],
    )
    def study_plan_document_tables(
        document_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> DatasetPage:
        return DatasetPage(
            **page_dataset(
                "study_plan_tables",
                offset=offset,
                limit=limit,
                query=None,
                row_id=None,
                document_id=document_id,
                table_id=None,
                discipline_id=None,
                major_id=None,
                program_id=None,
                department_id=None,
                slug=None,
            )
        )

    @app.get(
        "/api/v1/study-plans/documents/{document_id}/disciplines",
        response_model=DatasetPage,
        tags=["study plans"],
    )
    def study_plan_document_disciplines(
        document_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> DatasetPage:
        return DatasetPage(
            **page_dataset(
                "study_plan_disciplines",
                offset=offset,
                limit=limit,
                query=None,
                row_id=None,
                document_id=document_id,
                table_id=None,
                discipline_id=None,
                major_id=None,
                program_id=None,
                department_id=None,
                slug=None,
            )
        )

    @app.get("/api/v1/study-plans/documents/{document_id}/file", tags=["study plans"])
    def study_plan_document_file(document_id: str) -> FileResponse:
        file_info = repository.document_file(document_id)
        if file_info is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Файл учебного плана не найден",
            )
        path, filename, content_type = file_info
        return FileResponse(path, media_type=content_type, filename=filename)

    @app.post(
        "/api/v1/operations",
        response_model=OperationStatus,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["operations"],
    )
    def start_operation(
        request: OperationRequest,
        _access: None = Depends(require_write_access),
    ) -> OperationStatus:
        try:
            record = jobs.submit(
                request.operation,
                lambda: operation_executor(request, api_settings.result_dir),
            )
        except OperationConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
        return OperationStatus(**record)

    @app.get(
        "/api/v1/operations/{operation_id}",
        response_model=OperationStatus,
        tags=["operations"],
    )
    def operation(operation_id: str) -> OperationStatus:
        record = jobs.get(operation_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Операция не найдена: {operation_id}",
            )
        return OperationStatus(**record)

    return app


app = create_app()
