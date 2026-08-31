from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bmstu_parser.api.app import create_app
from bmstu_parser.api.config import ApiSettings


def _write_fixture(result_dir: Path) -> None:
    data_dir = result_dir / "study_plan_data"
    data_dir.mkdir(parents=True)
    (result_dir / "majors.csv").write_text(
        "id,slug,code,name\nmajor-1,example-010101,01.01.01,Example major\n",
        encoding="utf-8",
    )
    (result_dir / "educational_programs.csv").write_text(
        "id,major_id,department_id,code,name\nprogram-1,major-1,department-1,01.01.01-01,Example program\n",
        encoding="utf-8",
    )
    (result_dir / "parse_report.json").write_text(
        json.dumps({"verification": {"passed": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (data_dir / "study_plan_extraction_report.json").write_text(
        json.dumps({"verification": {"passed": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (data_dir / "study_plan_semantic_report.json").write_text(
        json.dumps({"verification": {"passed": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    study_plan = result_dir / "study_plans" / "example"
    study_plan.mkdir(parents=True)
    pdf_path = study_plan / "plan.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\nfixture")
    (data_dir / "study_plan_documents.jsonl").write_text(
        json.dumps(
            {
                "document_id": "document-1",
                "local_path": "study_plans/example/plan.pdf",
                "absolute_path": str(pdf_path),
                "kind": "pdf",
                "status": "ok",
                "expected_mime_type": "application/pdf",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (data_dir / "study_plan_tables.jsonl").write_text(
        json.dumps({"id": "table-1", "document_id": "document-1", "section": "curriculum"}) + "\n",
        encoding="utf-8",
    )


def test_api_exposes_swagger_catalog_and_safe_file_download(tmp_path: Path) -> None:
    result_dir = tmp_path / "result"
    _write_fixture(result_dir)

    with TestClient(create_app(ApiSettings(result_dir=result_dir))) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.headers["x-content-type-options"] == "nosniff"
        assert health.headers["x-frame-options"] == "DENY"
        assert health.headers["x-request-id"]

        docs = client.get("/docs")
        assert docs.status_code == 200
        assert "swagger-ui" in docs.text

        openapi = client.get("/openapi.json")
        assert openapi.status_code == 200
        assert "/api/v1/operations" in openapi.json()["paths"]
        operation_properties = openapi.json()["components"]["schemas"]["OperationRequest"]["properties"]
        assert operation_properties["reader_backend"]["default"] == "native"
        assert operation_properties["resume"]["default"] is True
        runs = client.get("/api/v1/runs")
        assert runs.status_code == 200
        assert runs.json()["items"] == []

        page = client.get("/api/v1/majors", params={"code": "01.01.01", "limit": 1})
        assert page.status_code == 200
        assert page.json()["total"] == 1
        assert page.json()["items"][0]["slug"] == "example-010101"

        document = client.get("/api/v1/study-plans/documents/document-1")
        assert document.status_code == 200
        download = client.get("/api/v1/study-plans/documents/document-1/file")
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/pdf"
        assert download.content.startswith(b"%PDF-")


def test_api_requires_key_for_operations_and_tracks_job(tmp_path: Path) -> None:
    result_dir = tmp_path / "result"
    _write_fixture(result_dir)

    def fake_operation(_request: object, _result_dir: Path) -> dict[str, object]:
        return {"operation": "fake", "quality": {"verification": {"passed": True}}}

    settings = ApiSettings(result_dir=result_dir, api_key="secret")
    with TestClient(create_app(settings, operation_executor=fake_operation)) as client:
        payload = {"operation": "extract_semantics", "strict": True}
        assert client.post("/api/v1/operations", json=payload).status_code == 401

        started = client.post("/api/v1/operations", json=payload, headers={"X-API-Key": "secret"})
        assert started.status_code == 202
        operation_id = started.json()["id"]

        for _ in range(50):
            operation = client.get(f"/api/v1/operations/{operation_id}").json()
            if operation["status"] == "succeeded":
                break
            time.sleep(0.01)
        assert operation["status"] == "succeeded"
        assert operation["result"]["quality"]["verification"]["passed"] is True


def test_local_file_dashboard_origin_is_allowed_by_default(tmp_path: Path, monkeypatch: object) -> None:
    result_dir = tmp_path / "result"
    _write_fixture(result_dir)
    monkeypatch.setenv("BMSTU_ENV", "development")
    monkeypatch.setenv("BMSTU_CORS_ORIGINS", "")
    monkeypatch.setenv("BMSTU_RESULT_DIR", str(result_dir))

    settings = replace(ApiSettings.from_env(), result_dir=result_dir)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health", headers={"Origin": "null"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "null"


def test_production_api_requires_write_key_at_startup(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="BMSTU_API_KEY"):
        create_app(ApiSettings(result_dir=tmp_path, environment="production"))
