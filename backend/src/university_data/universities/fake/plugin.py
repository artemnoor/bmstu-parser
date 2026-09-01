from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ...core.capabilities import UniversityCapabilities
from ...core.config import ResolverSpec, load_plugin_config
from ...core.plugin import (
    ResolverRegistry,
    UniversityConfig,
    UniversityManifest,
    UniversityOperations,
    UniversityProviders,
)
from ...core.source_models import (
    SourceAdmissionRequirement,
    SourceCurriculum,
    SourceProgram,
    SourceTeacher,
)
from ...domain.provenance import SourceProvenance
from ...sources.xlsx import XlsxExtractor

ROOT = Path(__file__).parent


def _provenance(source_key: str, path: str) -> SourceProvenance:
    return SourceProvenance(
        source_page=f"file:///{path}",
        raw_snapshot_path=path,
        source_key=source_key,
    )


class FakeProgramsProvider:
    capability = "programs"
    persists_raw = True

    def fetch(self) -> list[SourceProgram]:
        payload = json.loads(
            (ROOT / "fixtures/programs.json").read_text(encoding="utf-8")
        )
        return [
            SourceProgram(
                source_key=str(item["id"]),
                name=str(item.get("name", "")),
                code=str(item.get("code", "")),
                study_direction_key=str(item.get("study_direction", "")),
                description=str(item.get("description", "")),
                raw=item,
                provenance=_provenance(str(item["id"]), "fixtures/programs.json"),
            )
            for item in payload
            if isinstance(item, dict)
        ]


class FakeTeachersProvider:
    capability = "teachers"
    persists_raw = True

    def fetch(self) -> list[SourceTeacher]:
        payload = json.loads(
            (ROOT / "fixtures/teachers.json").read_text(encoding="utf-8")
        )
        return [
            SourceTeacher(
                source_key=str(item["id"]),
                name=str(item.get("name", "")),
                position=str(item.get("position", "")),
                # Departments are intentionally unsupported by this plugin;
                # retain the source label in extensions instead of emitting a
                # canonical link to a non-existent target.
                department_key="",
                email=str(item.get("email", "")),
                raw=item,
                extensions={
                    key: value
                    for key, value in {
                        "teacher_rating": item.get("teacher_rating"),
                        "source_department": item.get("department", ""),
                    }.items()
                    if value not in (None, "")
                },
                provenance=_provenance(str(item["id"]), "fixtures/teachers.json"),
            )
            for item in payload
            if isinstance(item, dict)
        ]


class FakeAdmissionProvider:
    capability = "admission"
    persists_raw = True

    def fetch(self) -> list[SourceAdmissionRequirement]:
        return [
            SourceAdmissionRequirement(
                source_key="fi-program-analytics:math",
                subject="Математика",
                minimum_score=60,
                raw={"program": "fi-program-analytics", "subject": "Математика"},
                provenance=_provenance(
                    "fi-program-analytics:math", "fixtures/programs.json"
                ),
            )
        ]


class FakeCurriculumProvider:
    capability = "curricula"
    persists_raw = True

    def __init__(self) -> None:
        self.extractor = XlsxExtractor()

    def _fixture_path(self) -> Path:
        configured = ROOT / "fixtures/curriculum.xlsx"
        if configured.is_file():
            return configured
        directory = Path(tempfile.gettempdir()) / "university_data_fake"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "curriculum.xlsx"
        if not path.exists():
            from openpyxl import Workbook

            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Curriculum"
            sheet.append(["program", "discipline", "semester", "hours", "credits"])
            sheet.append(["fi-program-analytics", "Статистика", 1, None, 4])
            sheet.append(["fi-program-analytics", "Математика", 1, 72, 2])
            sheet.merge_cells("A2:A3")
            workbook.save(path)
            workbook.close()
        return path

    def fetch(self) -> list[SourceCurriculum]:
        path = self._fixture_path()
        rows = tuple(self.extractor.rows(path, sheet="Curriculum"))
        return [
            SourceCurriculum(
                source_key="curriculum-fi",
                name="Fake curriculum",
                program_key="fi-program-analytics",
                path=path,
                rows=rows,
                raw={"path": str(path), "row_count": len(rows)},
                provenance=_provenance("curriculum-fi", "fixtures/curriculum.xlsx"),
            )
        ]


class FakeUniversityPlugin:
    university_id = "fake"
    display_name = "Fake University"

    def capabilities(self) -> UniversityCapabilities:
        config = load_plugin_config(ROOT / "manifest.yaml")
        return UniversityCapabilities(**config.capabilities)

    def manifest(self) -> UniversityManifest:
        config = load_plugin_config(ROOT / "manifest.yaml")
        return UniversityManifest(
            university_id=config.university_id,
            display_name=config.display_name,
            capabilities=UniversityCapabilities(**config.capabilities).specs(
                allow_partial=config.allow_partial
            ),
            module_version=config.module_version,
            config_path=ROOT / "manifest.yaml",
            settings=config.settings,
        )

    def providers(self, options: object | None = None) -> UniversityProviders:
        return UniversityProviders(
            programs=FakeProgramsProvider(),
            curricula=FakeCurriculumProvider(),
            admission=FakeAdmissionProvider(),
            teachers=FakeTeachersProvider(),
        )

    def resolvers(self) -> ResolverRegistry:
        config = load_plugin_config(ROOT / "manifest.yaml")
        return ResolverRegistry(specs=config.resolvers)

    def config(self) -> UniversityConfig:
        config = load_plugin_config(ROOT / "manifest.yaml")
        return UniversityConfig(
            university_id=config.university_id,
            display_name=config.display_name,
            config_path=ROOT / "manifest.yaml",
            settings=config.settings,
        )

    def resolver_specs(self, field: str) -> tuple[ResolverSpec, ...]:
        config = load_plugin_config(ROOT / "manifest.yaml")
        return config.resolvers.get(field, ())

    def resolver_builders(
        self, field: str
    ) -> Mapping[str, Callable[[ResolverSpec], Any]]:
        return {}

    def operations(self) -> UniversityOperations:
        return _UnsupportedOperations()


class _UnsupportedOperations:
    def execute(self, request: Any, result_dir: Path) -> dict[str, Any]:
        raise ValueError(
            "Fake University exposes refresh only; this operation is not supported"
        )
