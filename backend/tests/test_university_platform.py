from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from university_data import REGISTRY
from university_data.api.app import create_app
from university_data.api.config import ApiSettings
from university_data.core.capabilities import UniversityCapabilities
from university_data.core.config import load_plugin_config
from university_data.core.contracts import (
    ProviderContractError,
    validate_provider_output,
)
from university_data.core.plugin import UniversityProviders
from university_data.core.registry import UniversityRegistry
from university_data.core.source_models import SourceCurriculum, SourceProgram
from university_data.domain.ids import (
    deterministic_source_keys,
    global_stable_id,
)
from university_data.domain.provenance import SourceProvenance
from university_data.migrations import migrate_bmstu
from university_data.ontology import build_ontology
from university_data.pipeline import PipelineOptions, UniversityPipeline
from university_data.quality import build_quality_report
from university_data.resolvers import CreditsToHoursResolver, ResolverChain
from university_data.sources.xlsx import XlsxExtractor
from university_data.universities.bmstu.adapter.study_plans.semantic_source import (
    parse_source_curriculum,
)
from university_data.universities.hse.plugin import HseProgramsProvider


def test_global_ids_are_scoped_and_reorder_stable() -> None:
    first = [global_stable_id("fake", "program", value) for value in ("a", "b")]
    second = [global_stable_id("fake", "program", value) for value in ("b", "a")]
    assert set(first) == set(second)
    assert first[0] != global_stable_id("bmstu", "program", "a")
    assert first[0].startswith("university:fake:program:")


def test_curriculum_source_keys_use_business_identity_not_row_position() -> None:
    rows = [
        {"code": "101", "discipline": "Алгебра", "department": "МТ"},
        {"code": "202", "discipline": "Физика", "department": "ФТ"},
    ]
    first = deterministic_source_keys(rows, key=lambda row: row.values())
    second = deterministic_source_keys(
        list(reversed(rows)), key=lambda row: row.values()
    )
    assert set(first) == set(second)
    assert all("index" not in key for key in first)


def test_provider_contract_rejects_wrong_dto_and_duplicate_source_key() -> None:
    class WrongProvider:
        capability = "programs"

        def fetch(self) -> list[object]:
            return [SourceCurriculum(source_key="wrong")]

    with pytest.raises(ProviderContractError, match="SourceProgram"):
        validate_provider_output("programs", WrongProvider(), WrongProvider().fetch())

    class DuplicateProvider:
        capability = "programs"

        def fetch(self) -> list[SourceProgram]:
            return [SourceProgram(source_key="same"), SourceProgram(source_key="same")]

    provider = DuplicateProvider()
    with pytest.raises(ProviderContractError, match="duplicate source_key"):
        validate_provider_output("programs", provider, provider.fetch())


def test_pipeline_rejects_invalid_provider_contract_before_publication(
    tmp_path: Path,
) -> None:
    class BadProvider:
        capability = "programs"

        def fetch(self) -> list[object]:
            return [SourceCurriculum(source_key="not-a-program")]

    class BadPlugin:
        university_id = "bad"
        display_name = "Bad University"

        def capabilities(self) -> UniversityCapabilities:
            return UniversityCapabilities(programs=True)

        def providers(self, options: object | None = None) -> UniversityProviders:
            return UniversityProviders(programs=BadProvider())

    with pytest.raises(ProviderContractError, match="SourceProgram"):
        UniversityPipeline(UniversityRegistry((BadPlugin(),))).run(
            "bad", PipelineOptions(output_dir=tmp_path)
        )


def test_quality_gate_reports_duplicate_canonical_ids() -> None:
    record = {
        "id": "same-id",
        "university_id": "fake",
        "provenance": {},
    }
    report = build_quality_report(
        "fake",
        {"programs": True},
        {"universities": [], "programs": [record, dict(record)]},
    )
    assert report["verification"]["passed"] is False
    assert report["duplicates"] == {"programs": ["same-id"]}


def test_quality_gate_reports_broken_links_explicitly() -> None:
    university_id = global_stable_id("fake", "university", "fake")
    records = {
        "universities": [{"id": university_id, "university_id": "fake"}],
        "programs": [
            {
                "id": "program-1",
                "university_id": "fake",
                "department_id": "missing-department",
            }
        ],
    }
    ontology = build_ontology("fake", records)
    assert len(ontology["broken_links"]) == 1
    report = build_quality_report(
        "fake", {"programs": True}, records, ontology=ontology
    )
    assert report["verification"]["passed"] is False
    assert report["checks"]["orphan_links"] == 1


def test_hse_real_catalog_adapter_parses_official_card_shape(tmp_path: Path) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get_text(self, url: str) -> str:
            self.urls.append(url)
            if url.endswith("/page/2"):
                return (
                    '<a href="https://www.hse.ru/ba/second" class="e-card">'
                    '<div class="e-card__category">02.03.04 Второе направление</div>'
                    '<h3><span class="e-card__title-inner">Вторая программа</span></h3>'
                    "</a>"
                )
            return (
                '<link rel="next" href="/n/education/bachelor/page/2">'
                '<a href="https://www.hse.ru/ba/first" class="e-card">'
                '<div class="e-card__category">01.03.01 Математика</div>'
                '<h3><span class="e-card__title-inner">Прикладная математика</span></h3>'
                '</a><a href="https://www.hse.ru/ba/first" class="e-card">'
                '<div class="e-card__category">01.03.01 Математика</div>'
                '<h3><span class="e-card__title-inner">Прикладная математика</span></h3>'
                "</a>"
            )

    client = FakeClient()
    provider = HseProgramsProvider(PipelineOptions(output_dir=tmp_path), client=client)
    programs = provider.fetch()
    assert [item.code for item in programs] == ["01.03.01", "02.03.04"]
    assert programs[0].source_key == "https://www.hse.ru/ba/first"
    assert (tmp_path / "hse/raw/catalog-page-2.html").is_file()


def test_pdf_semantics_returns_typed_source_curriculum_for_generic_pipeline() -> None:
    class FakePdfReader:
        name = "fixture-pdf"

        def extract(
            self, path: Path, document_id: str
        ) -> tuple[list, list, str, list[str]]:
            cells: list[dict[str, object]] = []

            def add(
                row: int, column: int, text: str, left: float, right: float
            ) -> None:
                cells.append(
                    {
                        "id": f"cell-{row}-{column}",
                        "table_id": "table-pdf",
                        "row_index": row,
                        "column_index": column,
                        "text": text,
                        "bbox": {
                            "x0": left,
                            "x1": right,
                            "top": row,
                            "bottom": row + 1,
                        },
                        "word_ids": [],
                    }
                )

            for column, text, left, right in [
                (0, "Шифр", 0, 5),
                (1, "Наименование", 5, 10),
                (2, "Кафедра", 10, 15),
                (10, "1 - 17 недель", 50, 75),
                (11, "2 - 17 недель", 75, 100),
            ]:
                add(0, column, text, left, right)
            for column, text, left, right in [
                (3, "Общая, з.е.", 15, 20),
                (4, "Общая, час", 20, 25),
                (5, "Аудит. час", 25, 30),
                (6, "Лек", 30, 35),
                (7, "Сем", 35, 40),
                (8, "Лаб", 40, 45),
                (9, "Сам", 45, 50),
            ]:
                add(2, column, text, left, right)
            for column, text, left, right in [
                (0, "1", 0, 5),
                (1, "Алгебра", 5, 10),
                (2, "МТ", 10, 15),
                (3, "2", 15, 20),
                (4, "72", 20, 25),
                (5, "36", 25, 30),
                (6, "0", 30, 35),
                (7, "0", 35, 40),
                (8, "0", 40, 45),
                (9, "36", 45, 50),
                (10, "2", 50, 55),
                (11, "72", 55, 60),
                (12, "36", 60, 65),
                (13, "36", 65, 70),
                (14, "Экз", 70, 75),
            ]:
                add(4, column, text, left, right)
            table = {
                "id": "table-pdf",
                "document_id": document_id,
                "page_number": 1,
                "section": "curriculum",
                "bbox": {"x0": 0, "x1": 100, "top": 0, "bottom": 100},
                "rows": [
                    [cell for cell in cells if cell["row_index"] == row]
                    for row in (0, 2, 4)
                ],
            }
            return (
                [
                    {
                        "document_id": document_id,
                        "page_number": 1,
                        "words": [],
                    }
                ],
                [table],
                "Учебный план",
                [],
            )

    curriculum = parse_source_curriculum(
        Path("fixture.pdf"),
        document_id="document-pdf",
        program_key="program-pdf",
        name="PDF program",
        provenance=SourceProvenance(source_key="document-pdf"),
        reader_backend=FakePdfReader(),
    )
    assert isinstance(curriculum, SourceCurriculum)
    assert len(curriculum.rows) == 1
    assert curriculum.rows[0]["discipline"] == "Алгебра"
    assert len(curriculum.rows[0]["semester_loads"]) == 2
    assert curriculum.rows[0]["extensions"]["semantic_source_id"]


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
    universities = [
        json.loads(line)
        for line in (tmp_path / "fake/canonical/universities.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert universities[0]["id"].startswith("university:fake:university:")
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
            "hse",
        }
        assert client.get("/api/v1/universities/fake/programs").status_code == 200
        assert client.get("/api/v1/universities/fake/teachers").status_code == 200
        assert client.get("/api/v1/universities/fake/admission").status_code == 200
        unsupported = client.get("/api/v1/universities/fake/departments")
        assert unsupported.status_code == 404
        assert unsupported.json()["detail"]["code"] == "capability_unavailable"
        unsupported_rows = client.get(
            "/api/v1/universities/fake/datasets/departments/rows"
        )
        assert unsupported_rows.status_code == 404
        assert unsupported_rows.json()["detail"]["code"] == "capability_unavailable"
        hse_operation = client.post(
            "/api/v1/universities/hse/operations",
            json={"operation": "extract_semantics", "strict": True},
        )
        assert hse_operation.status_code == 404
        assert hse_operation.json()["detail"]["code"] == "capability_unavailable"
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
