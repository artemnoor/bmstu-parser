from __future__ import annotations

import hmac
import re
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from bmstu_parser.api.job_store import SqliteJobStore
from bmstu_parser.api.jobs import JobManager, OperationConflictError

from .. import __version__
from ..registry import REGISTRY
from .config import ApiSettings
from .models import (
    DatasetDescriptor,
    DatasetPage,
    OperationRequest,
    OperationStatus,
    UniversityDescriptor,
)
from .operations import execute_operation
from .repository import DatasetNotFoundError, DatasetRepository, DatasetUnavailableError

SERVICE_NAME = "university-data-api"


def create_app(
    settings: ApiSettings | None = None,
    *,
    registry: Any = REGISTRY,
    operation_executor: Callable[..., dict[str, Any]] = execute_operation,
    job_manager: JobManager | None = None,
) -> FastAPI:
    api_settings = settings or ApiSettings.from_env()
    if api_settings.is_production and not api_settings.api_key:
        raise RuntimeError("UNIVERSITY_API_KEY is required in production")
    jobs = job_manager or JobManager(
        store=SqliteJobStore(
            api_settings.result_dir / "_operations.sqlite3",
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
        title="University Data Platform API",
        version=__version__,
        summary="Scoped API for canonical university data",
        lifespan=lifespan,
    )
    app.state.settings = api_settings
    app.state.registry = registry
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

    def plugin_for(university_id: str) -> Any:
        try:
            return registry.require(university_id)
        except LookupError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "university_not_found", "message": str(exc)},
            ) from exc

    def require_capability(university_id: str, capability: str) -> Any:
        plugin = plugin_for(university_id)
        if not plugin.capabilities().supports(capability):
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "capability_unavailable",
                    "capability": capability,
                    "university_id": university_id,
                },
            )
        return plugin

    def repository_for(university_id: str) -> DatasetRepository:
        plugin = plugin_for(university_id)
        return DatasetRepository(api_settings.result_dir, plugin.university_id)

    def page_dataset(
        university_id: str,
        name: str,
        offset: int,
        limit: int,
        query: str | None,
        filters: dict[str, str | None],
    ) -> DatasetPage:
        repository = repository_for(university_id)
        try:
            payload = repository.page(
                name,
                offset=offset,
                limit=limit,
                query=query,
                filters={key: value for key, value in filters.items() if value},
            )
        except DatasetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "dataset_not_published", "message": str(exc)},
            ) from exc
        return DatasetPage(**payload)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"service": SERVICE_NAME, "docs": "/docs", "openapi": "/openapi.json"}

    @app.get("/health")
    def health() -> dict[str, Any]:
        ready = any(
            (api_settings.result_dir / item / "quality/report.json").is_file()
            for item in registry.ids()
        )
        return {
            "status": "ok" if ready else "degraded",
            "service": SERVICE_NAME,
            "version": __version__,
            "result_dir": str(api_settings.result_dir),
            "dataset_ready": ready,
        }

    @app.get(
        "/api/v1/universities",
        response_model=list[UniversityDescriptor],
        tags=["universities"],
    )
    def universities() -> list[UniversityDescriptor]:
        result = []
        for plugin in registry:
            capabilities = plugin.capabilities().as_dict()
            path = api_settings.result_dir / plugin.university_id
            result.append(
                UniversityDescriptor(
                    university_id=plugin.university_id,
                    display_name=plugin.display_name,
                    capabilities=capabilities,
                    capability_status={
                        key: "published" if value else "not_supported"
                        for key, value in capabilities.items()
                    },
                    data_ready=(path / "quality/report.json").is_file()
                    or (path / "parse_report.json").is_file(),
                )
            )
        return result

    @app.get(
        "/api/v1/universities/{university_id}",
        response_model=UniversityDescriptor,
        tags=["universities"],
    )
    def university(university_id: str) -> UniversityDescriptor:
        plugin = plugin_for(university_id)
        capabilities = plugin.capabilities().as_dict()
        path = api_settings.result_dir / plugin.university_id
        return UniversityDescriptor(
            university_id=plugin.university_id,
            display_name=plugin.display_name,
            capabilities=capabilities,
            capability_status={
                key: "published" if value else "not_supported"
                for key, value in capabilities.items()
            },
            data_ready=(path / "quality/report.json").is_file()
            or (path / "parse_report.json").is_file(),
        )

    @app.get("/api/v1/universities/{university_id}/catalog", tags=["catalog"])
    def catalog(university_id: str) -> dict[str, Any]:
        plugin_for(university_id)
        repository = repository_for(university_id)
        return {
            "university": university(university_id).model_dump(),
            "datasets": repository.descriptors(),
            "quality": repository.reports(),
        }

    @app.get(
        "/api/v1/universities/{university_id}/datasets",
        response_model=list[DatasetDescriptor],
        tags=["datasets"],
    )
    def datasets(university_id: str) -> list[DatasetDescriptor]:
        return [
            DatasetDescriptor(**item)
            for item in repository_for(university_id).descriptors()
        ]

    @app.get(
        "/api/v1/universities/{university_id}/datasets/{name}/rows",
        response_model=DatasetPage,
        tags=["datasets"],
    )
    def dataset_rows(
        university_id: str,
        name: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
        q: str | None = None,
        id: str | None = None,
        program_id: str | None = None,
        department_id: str | None = None,
    ) -> DatasetPage:
        return page_dataset(
            university_id,
            name,
            offset,
            limit,
            q,
            {"id": id, "program_id": program_id, "department_id": department_id},
        )

    @app.get(
        "/api/v1/universities/{university_id}/programs",
        response_model=DatasetPage,
        tags=["domain"],
    )
    def programs(
        university_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
        q: str | None = None,
        department_id: str | None = None,
    ) -> DatasetPage:
        require_capability(university_id, "programs")
        return page_dataset(
            university_id,
            "programs",
            offset,
            limit,
            q,
            {"department_id": department_id},
        )

    @app.get(
        "/api/v1/universities/{university_id}/curricula",
        response_model=DatasetPage,
        tags=["domain"],
    )
    def curricula(
        university_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
        q: str | None = None,
        program_id: str | None = None,
    ) -> DatasetPage:
        require_capability(university_id, "curricula")
        return page_dataset(
            university_id, "curricula", offset, limit, q, {"program_id": program_id}
        )

    @app.get(
        "/api/v1/universities/{university_id}/departments",
        response_model=DatasetPage,
        tags=["domain"],
    )
    def departments(
        university_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
        q: str | None = None,
    ) -> DatasetPage:
        require_capability(university_id, "departments")
        return page_dataset(university_id, "departments", offset, limit, q, {})

    @app.get(
        "/api/v1/universities/{university_id}/faculties",
        response_model=DatasetPage,
        tags=["domain"],
    )
    def faculties(
        university_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
        q: str | None = None,
    ) -> DatasetPage:
        require_capability(university_id, "faculties")
        return page_dataset(university_id, "faculties", offset, limit, q, {})

    @app.get(
        "/api/v1/universities/{university_id}/admission",
        response_model=DatasetPage,
        tags=["domain"],
    )
    def admission(
        university_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
        q: str | None = None,
    ) -> DatasetPage:
        require_capability(university_id, "admission")
        return page_dataset(
            university_id, "admission_requirements", offset, limit, q, {}
        )

    @app.get(
        "/api/v1/universities/{university_id}/tuition",
        response_model=DatasetPage,
        tags=["domain"],
    )
    def tuition(
        university_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
        q: str | None = None,
    ) -> DatasetPage:
        require_capability(university_id, "tuition")
        return page_dataset(university_id, "tuition_options", offset, limit, q, {})

    @app.get(
        "/api/v1/universities/{university_id}/teachers",
        response_model=DatasetPage,
        tags=["domain"],
    )
    def teachers(
        university_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
        q: str | None = None,
        department_id: str | None = None,
    ) -> DatasetPage:
        require_capability(university_id, "teachers")
        return page_dataset(
            university_id,
            "teachers",
            offset,
            limit,
            q,
            {"department_id": department_id},
        )

    def require_write_access(
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> None:
        if api_settings.api_key and not hmac.compare_digest(
            x_api_key or "", api_settings.api_key
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing X-API-Key",
            )

    @app.post(
        "/api/v1/universities/{university_id}/operations",
        response_model=OperationStatus,
        status_code=202,
        tags=["operations"],
    )
    def start_operation(
        university_id: str,
        request: OperationRequest,
        _access: None = Depends(require_write_access),
    ) -> OperationStatus:
        plugin = plugin_for(university_id)
        try:
            record = jobs.submit(
                request.operation,
                lambda: operation_executor(
                    request, api_settings.result_dir, plugin.university_id, registry
                ),
            )
        except OperationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return OperationStatus(university_id=plugin.university_id, **record)

    @app.get(
        "/api/v1/universities/{university_id}/operations/{operation_id}",
        response_model=OperationStatus,
        tags=["operations"],
    )
    def operation(university_id: str, operation_id: str) -> OperationStatus:
        plugin = plugin_for(university_id)
        record = jobs.get(operation_id)
        if record is None:
            raise HTTPException(
                status_code=404, detail=f"Operation not found: {operation_id}"
            )
        result = record.get("result")
        if isinstance(result, dict) and result.get("university_id") not in {
            None,
            plugin.university_id,
        }:
            raise HTTPException(
                status_code=404, detail=f"Operation not found: {operation_id}"
            )
        return OperationStatus(university_id=plugin.university_id, **record)

    return app


app = create_app()
