from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from university_data import REGISTRY
from university_data.api.app import create_app
from university_data.api.config import ApiSettings
from university_data.core.capabilities import CapabilitySpec, UniversityCapabilities
from university_data.core.config import ResolverSpec, load_plugin_config
from university_data.core.contracts import (
    ProviderContractError,
    validate_provider_output,
)
from university_data.core.plugin import (
    DataGap,
    ProviderResult,
    ProviderSet,
    ResolverRegistry,
    UniversityManifest,
    UniversityProviders,
)
from university_data.core.registry import UniversityRegistry
from university_data.core.source_models import (
    SourceAdmissionRequirement,
    SourceCurriculum,
    SourceDepartment,
    SourceFaculty,
    SourceProgram,
    SourceTeacher,
    SourceTuition,
)
from university_data.domain.aliases import build_id_aliases
from university_data.domain.ids import (
    canonical_source_key,
    deterministic_source_keys,
    global_stable_id,
)
from university_data.domain.provenance import SourceProvenance
from university_data.migrations import migrate_bmstu
from university_data.ontology import build_ontology
from university_data.pipeline import PipelineOptions, UniversityPipeline
from university_data.quality import build_quality_report
from university_data.resolvers import CreditsToHoursResolver, Resolution, ResolverChain
from university_data.sources.xlsx import XlsxExtractor
from university_data.storage import UniversityStorage
from university_data.universities.bmstu.adapter.study_plans.semantic_source import (
    parse_source_curriculum,
)
from university_data.universities.hse.plugin import HsePlugin, HseProgramsProvider


def _test_provenance(source_key: str) -> SourceProvenance:
    return SourceProvenance(
        source_page="https://hse.example/catalog",
        detail_page="https://hse.example/catalog/item",
        source_key=source_key,
    )


class _StaticProvider:
    def __init__(self, capability: str, items: list[object]) -> None:
        self.capability = capability
        self.items = items

    def fetch(self) -> list[object]:
        return self.items


class _HseCatalogClient:
    def get_text(self, _url: str) -> str:
        return (
            '<a href="https://www.hse.ru/ba/analytics" class="e-card">'
            '<div class="e-card__category">01.03.01 Математика</div>'
            '<h3><span class="e-card__title-inner">Аналитика данных</span></h3>'
            "</a>"
        )


class _HseFixedHoursResolver:
    name = "hse_fixed_hours"

    def resolve(self, _source: dict[str, object]) -> Resolution[int]:
        return Resolution(42, "derived", self.name, 0.95)


class _ExtendedHsePlugin(HsePlugin):
    university_id = "hse"
    display_name = "HSE extension fixture"

    def capabilities(self) -> UniversityCapabilities:
        return UniversityCapabilities(
            programs=True,
            curricula=True,
            faculties=True,
            departments=True,
            admission=True,
            tuition=True,
            teachers=True,
        )

    def providers(self, options: PipelineOptions | None = None) -> UniversityProviders:
        if options is None:
            options = PipelineOptions()
        program_key = "https://www.hse.ru/ba/analytics"
        curriculum_key = f"{program_key}/curriculum"
        return UniversityProviders(
            programs=HseProgramsProvider(options, client=_HseCatalogClient()),
            faculties=_StaticProvider(
                "faculties",
                [
                    SourceFaculty(
                        source_key="hse-faculty",
                        name="Факультет компьютерных наук",
                        provenance=_test_provenance("hse-faculty"),
                    )
                ],
            ),
            departments=_StaticProvider(
                "departments",
                [
                    SourceDepartment(
                        source_key="hse-department",
                        name="Кафедра анализа данных",
                        faculty_key="hse-faculty",
                        provenance=_test_provenance("hse-department"),
                    )
                ],
            ),
            curricula=_StaticProvider(
                "curricula",
                [
                    SourceCurriculum(
                        source_key=curriculum_key,
                        name="Учебный план аналитики данных",
                        program_key=program_key,
                        rows=(
                            {
                                "code": "MATH",
                                "discipline": "Математический анализ",
                                "semester": 1,
                            },
                        ),
                        provenance=_test_provenance(curriculum_key),
                    )
                ],
            ),
            admission=_StaticProvider(
                "admission",
                [
                    SourceAdmissionRequirement(
                        source_key="hse-admission-math",
                        subject="Математика",
                        minimum_score=70,
                        program_key=program_key,
                        provenance=_test_provenance("hse-admission-math"),
                    )
                ],
            ),
            tuition=_StaticProvider(
                "tuition",
                [
                    SourceTuition(
                        source_key="hse-tuition-full-time",
                        study_form="очная",
                        value=450000,
                        currency="RUB",
                        term="2026",
                        program_key=program_key,
                        provenance=_test_provenance("hse-tuition-full-time"),
                    )
                ],
            ),
            teachers=_StaticProvider(
                "teachers",
                [
                    SourceTeacher(
                        source_key="hse-teacher-1",
                        name="Иван Иванов",
                        department_key="hse-department",
                        provenance=_test_provenance("hse-teacher-1"),
                    )
                ],
            ),
        )

    def resolver_specs(self, field: str) -> tuple[ResolverSpec, ...]:
        return (ResolverSpec(type="hse_fixed_hours"),) if field == "total_hours" else ()

    def resolver_builders(
        self, field: str
    ) -> Mapping[str, Callable[[ResolverSpec], object]]:
        return (
            {"hse_fixed_hours": lambda _spec: _HseFixedHoursResolver()}
            if field == "total_hours"
            else {}
        )


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
            provenance = _test_provenance("same")
            return [
                SourceProgram(source_key="same", provenance=provenance),
                SourceProgram(source_key="same", provenance=provenance),
            ]

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


def test_quality_gate_rejects_empty_supported_capability() -> None:
    report = build_quality_report(
        "fake",
        {"programs": True},
        {"universities": []},
    )
    assert report["capability_status"]["programs"] == "not_published"
    assert report["verification"]["passed"] is False
    assert "produced no canonical records" in report["errors"][0]


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
        "faculties": [
            {
                "slug": "migration-faculty",
                "title": "Migration faculty",
                "chairs": [
                    {
                        "slug": "migration-chair",
                        "title": "Migration chair",
                        "educationalProgram": {
                            "items": [{"code": "P-1", "name": "Migration program"}]
                        },
                    }
                ],
            }
        ],
    }
    detail = {
        "additional": {"name": "Migration major", "code": "01.03.01"},
        "chairs": {
            "items": [
                {
                    "slug": "migration-chair",
                    "title": "Migration chair",
                    "faculty": {
                        "slug": "migration-faculty",
                        "title": "Migration faculty",
                    },
                    "educationalProgram": {
                        "items": [{"code": "P-1", "name": "Migration program"}]
                    },
                }
            ]
        },
        "points": [{"title": "Математика", "point": "40", "isChoice": False}],
        "price": [{"studyForm": "очная", "term": "2026", "value": "100000"}],
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


def test_provider_contract_requires_real_locator_and_raw_lineage() -> None:
    class MissingLocatorProvider:
        capability = "programs"

    missing_locator = SourceProgram(
        source_key="program-1",
        provenance=SourceProvenance(source_key="program-1"),
    )
    with pytest.raises(ProviderContractError, match="real source URL/page"):
        validate_provider_output(
            "programs", MissingLocatorProvider(), [missing_locator]
        )

    class MissingRawProvider:
        capability = "programs"
        persists_raw = True

    missing_raw = SourceProgram(
        source_key="program-1",
        provenance=SourceProvenance(
            source_page="https://hse.example/program-1", source_key="program-1"
        ),
    )
    with pytest.raises(ProviderContractError, match="raw snapshot lineage"):
        validate_provider_output("programs", MissingRawProvider(), [missing_raw])


def test_url_source_ids_are_canonical_and_aliases_are_university_neutral(
    tmp_path: Path,
) -> None:
    first = "HTTPS://EXAMPLE.COM:443/catalog/program/?b=2&a=1#fragment"
    second = "https://example.com/catalog/program?a=1&b=2"
    assert canonical_source_key(first) == second
    assert global_stable_id("example", "program", first) == global_stable_id(
        "example", "program", second
    )
    automatic_aliases = build_id_aliases(
        {"programs": [{"id": "old-program", "provenance": {"source_key": first}}]},
        {"programs": [{"id": "new-program", "provenance": {"source_key": second}}]},
    )
    assert automatic_aliases == [
        {
            "legacy_id": "old-program",
            "canonical_id": "new-program",
            "entity_type": "program",
        }
    ]

    class AliasProvider:
        capability = "programs"

        def fetch(self) -> list[SourceProgram]:
            return [
                SourceProgram(
                    source_key=second,
                    name="Alias program",
                    code="01.03.01",
                    study_direction_key="01.03.01",
                    legacy_ids=("legacy-program-1",),
                    provenance=_test_provenance(second),
                )
            ]

    class AliasPlugin:
        university_id = "example"
        display_name = "Example University"

        def capabilities(self) -> UniversityCapabilities:
            return UniversityCapabilities(programs=True)

        def providers(self, _options: object | None = None) -> UniversityProviders:
            return UniversityProviders(programs=AliasProvider())

    registry = UniversityRegistry((AliasPlugin(),))
    UniversityPipeline(registry).run(
        "example", PipelineOptions(output_dir=tmp_path, strict=True)
    )
    storage = UniversityStorage(tmp_path, "example")
    aliases = json.loads(
        (storage.active_path() / "id_aliases.json").read_text(encoding="utf-8")
    )
    assert {item["legacy_id"] for item in aliases["aliases"]} == {"legacy-program-1"}

    with TestClient(
        create_app(ApiSettings(result_dir=tmp_path), registry=registry)
    ) as client:
        response = client.get(
            "/api/v1/universities/example/datasets/programs/rows",
            params={"id": "legacy-program-1"},
        )
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_quality_gate_preserves_last_valid_published_snapshot_on_source_error(
    tmp_path: Path,
) -> None:
    class GatedProvider:
        capability = "programs"
        fail = False

        def fetch(self) -> list[SourceProgram]:
            if self.fail:
                raise RuntimeError("source unavailable")
            return [
                SourceProgram(
                    source_key="program-1",
                    name="Published program",
                    provenance=_test_provenance("program-1"),
                )
            ]

    class GatedPlugin:
        university_id = "gated"
        display_name = "Gated University"

        def __init__(self) -> None:
            self.provider = GatedProvider()

        def capabilities(self) -> UniversityCapabilities:
            return UniversityCapabilities(programs=True)

        def providers(self, _options: object | None = None) -> UniversityProviders:
            return UniversityProviders(programs=self.provider)

    plugin = GatedPlugin()
    registry = UniversityRegistry((plugin,))
    UniversityPipeline(registry).run(
        "gated", PipelineOptions(output_dir=tmp_path, strict=True)
    )
    storage = UniversityStorage(tmp_path, "gated")
    pointer_before = (storage.path / "current.json").read_text(encoding="utf-8")
    programs_before = (storage.active_path() / "canonical/programs.jsonl").read_bytes()

    plugin.provider.fail = True
    with pytest.raises(RuntimeError, match="Quality gate failed"):
        UniversityPipeline(registry).run(
            "gated", PipelineOptions(output_dir=tmp_path, strict=True)
        )

    assert (storage.path / "current.json").read_text(encoding="utf-8") == pointer_before
    assert (
        storage.active_path() / "canonical/programs.jsonl"
    ).read_bytes() == programs_before
    staging = tmp_path / ".staging"
    assert not staging.exists() or not list(staging.iterdir())


def test_hse_can_extend_capabilities_and_serve_all_canonical_datasets(
    tmp_path: Path,
) -> None:
    registry = UniversityRegistry((_ExtendedHsePlugin(),))
    report = UniversityPipeline(registry).run(
        "hse", PipelineOptions(output_dir=tmp_path, strict=True)
    )
    assert report["verification"]["passed"] is True

    storage = UniversityStorage(tmp_path, "hse")
    disciplines = [
        json.loads(line)
        for line in (storage.active_path() / "canonical/disciplines.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert disciplines[0]["total_hours"] == 42
    assert disciplines[0]["field_meta"]["total_hours"]["method"] == ("hse_fixed_hours")
    directions = [
        json.loads(line)
        for line in (storage.active_path() / "canonical/study_directions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert directions[0]["name"] == "Математика"

    canonical_datasets = (
        "universities",
        "faculties",
        "departments",
        "study_directions",
        "programs",
        "curricula",
        "teachers",
        "admission",
        "admission_requirements",
        "tuition_options",
        "disciplines",
        "semesters",
        "semester_loads",
    )
    with TestClient(
        create_app(ApiSettings(result_dir=tmp_path), registry=registry)
    ) as client:
        for dataset in canonical_datasets:
            response = client.get(f"/api/v1/universities/hse/datasets/{dataset}/rows")
            assert response.status_code == 200, (dataset, response.text)
            assert response.json()["total"] > 0


def test_hse_production_module_uses_manifest_and_capability_provider_set() -> None:
    plugin = HsePlugin()
    manifest = plugin.manifest()
    providers = plugin.providers(PipelineOptions())
    assert manifest.config_path is not None
    assert manifest.config_path.name == "manifest.yaml"
    assert manifest.capabilities_dict()["programs"] is True
    assert manifest.capabilities_dict()["departments"] is False
    assert set(providers) == {"programs"}


def test_new_module_without_departments_keeps_optional_reference_unresolved(
    tmp_path: Path,
) -> None:
    class ProgramsProvider:
        capability = "programs"
        persists_raw = False

        def fetch(self) -> list[SourceProgram]:
            return [
                SourceProgram(
                    source_key="https://minimal.example/programs/analytics",
                    name="Аналитика данных",
                    code="01.03.01",
                    study_direction_key="01.03.01",
                    department_key="missing-department",
                    provenance=_test_provenance(
                        "https://minimal.example/programs/analytics"
                    ),
                )
            ]

    class Operations:
        def execute(self, request: object, result_dir: Path) -> dict[str, object]:
            raise ValueError(f"unsupported operation: {request}")

    class MinimalModule:
        def manifest(self) -> UniversityManifest:
            return UniversityManifest(
                university_id="minimal",
                display_name="Minimal University",
                capabilities=(CapabilitySpec("programs", "enabled"),),
                module_version="1.0.0",
            )

        def providers(self, options: object | None = None) -> ProviderSet:
            return ProviderSet({"programs": ProgramsProvider()})

        def resolvers(self) -> ResolverRegistry:
            return ResolverRegistry()

        def operations(self) -> Operations:
            return Operations()

    registry = UniversityRegistry((MinimalModule(),))
    report = UniversityPipeline(registry).run(
        "minimal", PipelineOptions(output_dir=tmp_path, strict=True)
    )
    assert report["verification"]["passed"] is True
    assert report["capability_status"]["departments"] == "not_supported"
    storage = UniversityStorage(tmp_path, "minimal")
    assert not (storage.active_path() / "canonical/departments.jsonl").exists()
    program = json.loads(
        (storage.active_path() / "canonical/programs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert program["department_id"] == ""
    assert (
        program["extensions"]["minimal"]["unresolved_references"]["department_key"]
        == "missing-department"
    )
    assert report["capability_warnings"]["programs"]
    assert report["capability_gaps"]["programs"][0]["code"] == (
        "optional_relation_unresolved"
    )
    ontology = json.loads(
        (storage.active_path() / "ontology.json").read_text(encoding="utf-8")
    )
    assert ontology["broken_links"] == []

    with TestClient(
        create_app(ApiSettings(result_dir=tmp_path), registry=registry)
    ) as client:
        response = client.get("/api/v1/universities/minimal/departments")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "capability_unavailable"


def test_new_module_can_publish_explicit_degraded_provider_result(
    tmp_path: Path,
) -> None:
    class PartialProgramsProvider:
        capability = "programs"
        persists_raw = False

        def fetch(self) -> ProviderResult[SourceProgram]:
            source_key = "https://partial.example/programs/analytics"
            return ProviderResult(
                records=(
                    SourceProgram(
                        source_key=source_key,
                        name="Аналитика данных",
                        provenance=_test_provenance(source_key),
                    ),
                ),
                complete=False,
                warnings=("one catalog page was unavailable",),
                gaps=(
                    DataGap(
                        code="page_unavailable",
                        message="The second catalog page could not be fetched",
                        source_key="https://partial.example/catalog?page=2",
                    ),
                ),
            )

    class Operations:
        def execute(self, request: object, result_dir: Path) -> dict[str, object]:
            raise ValueError(f"unsupported operation: {request}")

    class PartialModule:
        def manifest(self) -> UniversityManifest:
            return UniversityManifest(
                university_id="partial",
                display_name="Partial University",
                capabilities=(
                    CapabilitySpec("programs", "enabled", allow_partial=True),
                ),
            )

        def providers(self, options: object | None = None) -> ProviderSet:
            return ProviderSet({"programs": PartialProgramsProvider()})

        def resolver_specs(self, field: str) -> tuple[ResolverSpec, ...]:
            return ()

        def resolver_builders(
            self, field: str
        ) -> Mapping[str, Callable[[ResolverSpec], object]]:
            return {}

        def operations(self) -> Operations:
            return Operations()

    report = UniversityPipeline(UniversityRegistry((PartialModule(),))).run(
        "partial", PipelineOptions(output_dir=tmp_path, strict=True)
    )
    assert report["verification"]["passed"] is True
    assert report["capability_status"]["programs"] == "degraded"
    assert report["capability_warnings"]["programs"] == [
        "one catalog page was unavailable"
    ]
    assert report["capability_gaps"]["programs"][0]["code"] == "page_unavailable"
    assert (UniversityStorage(tmp_path, "partial").path / "current.json").is_file()


def test_manifest_modules_scale_without_cross_university_collisions(
    tmp_path: Path,
) -> None:
    class Operations:
        def execute(self, request: object, result_dir: Path) -> dict[str, object]:
            raise ValueError(f"unsupported operation: {request}")

    def make_module(index: int) -> object:
        university_id = f"scale-{index:02d}"
        source_key = f"https://scale.example/{university_id}/programs/analytics"

        class ProgramsProvider:
            capability = "programs"
            persists_raw = False

            def fetch(self) -> list[SourceProgram]:
                return [
                    SourceProgram(
                        source_key=source_key,
                        name="Аналитика данных",
                        provenance=_test_provenance(source_key),
                    )
                ]

        class Module:
            def manifest(self) -> UniversityManifest:
                return UniversityManifest(
                    university_id=university_id,
                    display_name=f"Scale University {index}",
                    capabilities=(CapabilitySpec("programs", "enabled"),),
                )

            def providers(self, options: object | None = None) -> ProviderSet:
                return ProviderSet({"programs": ProgramsProvider()})

            def resolver_specs(self, field: str) -> tuple[ResolverSpec, ...]:
                return ()

            def resolver_builders(
                self, field: str
            ) -> Mapping[str, Callable[[ResolverSpec], object]]:
                return {}

            def operations(self) -> Operations:
                return Operations()

        return Module()

    modules = tuple(make_module(index) for index in range(50))
    registry = UniversityRegistry(modules)
    assert len(registry.ids()) == 50

    for university_id in registry.ids():
        report = UniversityPipeline(registry).run(
            university_id,
            PipelineOptions(output_dir=tmp_path, strict=True),
        )
        assert report["verification"]["passed"] is True

    program_ids = {
        json.loads(
            (
                UniversityStorage(tmp_path, university_id).active_path()
                / "canonical/programs.jsonl"
            )
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )["id"]
        for university_id in registry.ids()
    }
    assert len(program_ids) == 50
