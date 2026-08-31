from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

from university_data import REGISTRY
from university_data.api.app import create_app
from university_data.api.config import ApiSettings
from university_data.core.config import load_plugin_config
from university_data.domain.ids import global_stable_id
from university_data.migrations import migrate_bmstu
from university_data.pipeline import PipelineOptions, UniversityPipeline
from university_data.resolvers import CreditsToHoursResolver, ResolverChain
from university_data.sources.xlsx import XlsxExtractor


def test_global_ids_are_scoped_and_reorder_stable() -> None:
    first = [global_stable_id("fake", "program", value) for value in ("a", "b")]
    second = [global_stable_id("fake", "program", value) for value in ("b", "a")]
    assert set(first) == set(second)
    assert first[0] != global_stable_id("bmstu", "program", "a")
    assert first[0].startswith("university:fake:program:")


def test_plugin_contract_and_strict_yaml_config() -> None:
    for plugin in REGISTRY:
        capabilities = plugin.capabilities()
        providers = plugin.providers()
        for name in capabilities.supported():
            assert providers.for_capability(name) is not None
        assert plugin.config().university_id == plugin.university_id
    config = load_plugin_config(
        Path("src/university_data/universities/fake/config.yaml")
    )
    assert config.resolvers["total_hours"] == ()


def test_xlsx_extractor_expands_merged_cells(tmp_path: Path) -> None:
    path = tmp_path / "curriculum.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["program", "discipline"])
    sheet.append(["Program A", "Math"])
    sheet.append([None, "Physics"])
    sheet.merge_cells("A2:A3")
    workbook.save(path)
    workbook.close()

    rows = list(XlsxExtractor().rows(path))
    assert [row["program"] for row in rows] == ["Program A", "Program A"]


def test_resolver_chain_derives_hours_from_credits() -> None:
    resolution = ResolverChain([CreditsToHoursResolver()]).resolve({"credits": 4})
    assert resolution.value == 144
    assert resolution.status == "derived"
    assert resolution.method == "credits_to_hours"


def test_fake_pipeline_materializes_metadata_extensions_and_unsupported(
    tmp_path: Path,
) -> None:
    report = UniversityPipeline(REGISTRY).run(
        "fake", PipelineOptions(output_dir=tmp_path, strict=True)
    )
    assert report["verification"]["passed"] is True
    assert report["capability_status"]["departments"] == "not_supported"
    teachers = [
        json.loads(line)
        for line in (tmp_path / "fake/canonical/teachers.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert teachers[0]["university_id"] == "fake"
    assert teachers[0]["extensions"]["fake"]["teacher_rating"] == 4.8
    disciplines = [
        json.loads(line)
        for line in (tmp_path / "fake/canonical/disciplines.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(
        item["field_meta"]["total_hours"]["status"] == "not_published"
        for item in disciplines
    )


def test_scoped_api_exposes_capabilities_and_removes_flat_routes(
    tmp_path: Path,
) -> None:
    UniversityPipeline(REGISTRY).run("fake", PipelineOptions(output_dir=tmp_path))
    with TestClient(create_app(ApiSettings(result_dir=tmp_path))) as client:
        universities = client.get("/api/v1/universities")
        assert universities.status_code == 200
        assert {item["university_id"] for item in universities.json()} == {
            "bmstu",
            "fake",
        }
        assert client.get("/api/v1/universities/fake/programs").status_code == 200
        assert client.get("/api/v1/universities/fake/teachers").status_code == 200
        assert client.get("/api/v1/universities/fake/admission").status_code == 200
        unsupported = client.get("/api/v1/universities/fake/departments")
        assert unsupported.status_code == 404
        assert unsupported.json()["detail"]["code"] == "capability_unavailable"
        assert client.get("/api/v1/programs").status_code == 404
        assert client.get("/api/v1/universities/unknown").status_code == 404


def test_bmstu_raw_replay_migration_keeps_source_and_publishes_aliases(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy"
    details = source / "raw/details"
    details.mkdir(parents=True)
    summary = {
        "slug": "migration-major",
        "name": "Migration major",
        "code": "01.03.01",
        "faculties": [],
    }
    detail = {
        "additional": {"name": "Migration major", "code": "01.03.01"},
        "chairs": {"items": []},
    }
    (source / "raw/majors_list.json").write_text(
        json.dumps({"meta": {"count": 1}, "data": [summary]}), encoding="utf-8"
    )
    (details / "migration-major.json").write_text(
        json.dumps(
            {
                "summary": summary,
                "detail": detail,
                "error": None,
                "fetched_at_utc": "now",
            }
        ),
        encoding="utf-8",
    )
    target = tmp_path / "result/bmstu"

    report = migrate_bmstu(source, target)
    assert report["migration"]["replayed"] is True
    assert (target / "raw/majors_list.json").read_bytes() == (
        source / "raw/majors_list.json"
    ).read_bytes()
    aliases = json.loads((target / "id_aliases.json").read_text(encoding="utf-8"))
    assert aliases["schema_version"] == "2.0"
    assert (target / "canonical/programs.csv").is_file()
