from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .core.registry import UniversityRegistry
from .core.source_models import (
    SourceAdmissionRequirement,
    SourceCurriculum,
    SourceDepartment,
    SourceDiscipline,
    SourceFaculty,
    SourceProgram,
    SourceSemester,
    SourceSemesterLoad,
    SourceTeacher,
    SourceTuition,
)
from .domain.provenance import SourceProvenance
from .normalization import CanonicalNormalizer
from .ontology import build_ontology
from .quality import build_quality_report
from .resolvers import build_resolver_chain
from .runtime import PipelineRun
from .storage import UniversityStorage


@dataclass(frozen=True, slots=True)
class PipelineOptions:
    output_dir: Path = Path("data/result")
    workers: int = 4
    page_size: int = 100
    timeout: float = 30.0
    delay: float = 0.15
    resolve_plans: bool = True
    download_plans: bool = False
    strict: bool = False


def _now() -> str:
    return datetime.now(UTC).isoformat()


class UniversityPipeline:
    """Materialize every registered university through one typed pipeline.

    Providers only return source DTOs. Canonical domain dataclasses are the
    sole materialization contract, so ontology, quality and storage consume a
    consistent schema regardless of the source adapter.
    """

    def __init__(
        self,
        registry: UniversityRegistry,
        *,
        normalizer: CanonicalNormalizer | None = None,
    ) -> None:
        self.registry = registry
        self.normalizer = normalizer or CanonicalNormalizer()

    def run(
        self, university_id: str, options: PipelineOptions | None = None
    ) -> dict[str, Any]:
        options = options or PipelineOptions()
        plugin = self.registry.require(university_id)
        university_id = plugin.university_id
        pipeline_run = PipelineRun(
            options.output_dir / university_id, "university_pipeline"
        )
        capabilities = plugin.capabilities()
        providers = plugin.providers(options)
        records: dict[str, list[dict[str, Any]]] = {
            "universities": [
                self.normalizer.university(
                    university_id,
                    plugin.display_name,
                    SourceProvenance(source_key=university_id),
                ).to_dict()
            ],
            "faculties": [],
            "departments": [],
            "study_directions": [],
            "programs": [],
            "curricula": [],
            "teachers": [],
            "admission_requirements": [],
            "tuition_options": [],
            "disciplines": [],
            "semesters": [],
            "semester_loads": [],
        }
        errors: list[str] = []

        for capability in capabilities.supported():
            provider = providers.for_capability(capability)
            if provider is None:
                errors.append(
                    f"capability {capability} is declared but provider is missing"
                )
                continue
            try:
                source_items = provider.fetch()
                self._materialize_capability(
                    university_id, capability, source_items, plugin, records
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{capability}: {type(exc).__name__}: {exc}")

        ontology = build_ontology(university_id, records)
        quality = build_quality_report(
            university_id,
            capabilities.as_dict(),
            records,
            errors=errors,
            ontology=ontology,
        )
        storage = UniversityStorage(options.output_dir, university_id)
        storage.ensure()
        storage.write_json(
            "canonical/catalog.json",
            {
                "university_id": university_id,
                "records": records,
                "quality": quality,
                "generated_at_utc": _now(),
            },
        )
        storage.write_json("ontology.json", ontology)
        storage.write_json("quality/report.json", quality)
        for name, items in records.items():
            storage.write_jsonl(f"canonical/{name}.jsonl", items)
            storage.write_csv(f"canonical/{name}.csv", items)
        pipeline_run.stage(
            "source_ingestion",
            inputs=["raw"],
            outputs=["raw"],
            metadata={"capabilities": capabilities.as_dict()},
        )
        pipeline_run.stage(
            "canonical_materialization",
            inputs=["raw"],
            outputs=["canonical"],
            metadata={"records": {name: len(items) for name, items in records.items()}},
        )
        pipeline_run.stage(
            "ontology_projection",
            inputs=["canonical"],
            outputs=["ontology.json"],
            metadata={
                "objects": len(ontology.get("objects", [])),
                "links": len(ontology.get("links", [])),
            },
        )
        pipeline_run.stage(
            "quality_gate",
            inputs=["canonical", "ontology.json"],
            outputs=["quality/report.json"],
            quality=quality,
        )
        pipeline_run.finish(
            status="succeeded" if quality["verification"]["passed"] else "failed",
            quality=quality,
        )
        if options.strict and not quality["verification"]["passed"]:
            raise RuntimeError(f"Quality gate failed for {university_id}")
        return quality

    def _materialize_capability(
        self,
        university_id: str,
        capability: str,
        source_items: list[Any],
        plugin: Any,
        records: dict[str, list[dict[str, Any]]],
    ) -> None:
        if capability == "faculties":
            records["faculties"] = [
                self.normalizer.faculty(university_id, item).to_dict()
                for item in source_items
                if isinstance(item, SourceFaculty)
            ]
            return
        if capability == "departments":
            records["departments"] = [
                self.normalizer.department(university_id, item).to_dict()
                for item in source_items
                if isinstance(item, SourceDepartment)
            ]
            return
        if capability == "programs":
            self._programs(university_id, source_items, records)
            return
        if capability == "teachers":
            records["teachers"] = [
                self.normalizer.teacher(university_id, item).to_dict()
                for item in source_items
                if isinstance(item, SourceTeacher)
            ]
            return
        if capability == "admission":
            records["admission_requirements"] = [
                self.normalizer.admission(university_id, item).to_dict()
                for item in source_items
                if isinstance(item, SourceAdmissionRequirement)
            ]
            return
        if capability == "tuition":
            records["tuition_options"] = [
                self.normalizer.tuition(university_id, item).to_dict()
                for item in source_items
                if isinstance(item, SourceTuition)
            ]
            return
        if capability == "curricula":
            curricula, disciplines, semesters, loads = self._curricula(
                university_id, source_items, plugin
            )
            records["curricula"] = curricula
            records["disciplines"] = disciplines
            records["semesters"] = semesters
            records["semester_loads"] = loads

    def _programs(
        self,
        university_id: str,
        source_items: list[Any],
        records: dict[str, list[dict[str, Any]]],
    ) -> None:
        programs: list[dict[str, Any]] = []
        directions: dict[str, dict[str, Any]] = {}
        for item in source_items:
            if not isinstance(item, SourceProgram):
                continue
            direction_key = item.study_direction_key or item.code or item.name
            raw_name = str(item.raw.get("study_direction_name", "")).strip()
            raw_code = str(item.raw.get("study_direction_code", "")).strip()
            direction = self.normalizer.study_direction(
                university_id,
                key=direction_key,
                name=raw_name or direction_key,
                code=raw_code or direction_key,
                provenance=item.provenance,
            ).to_dict()
            directions.setdefault(direction_key, direction)
            programs.append(self.normalizer.program(university_id, item).to_dict())
        records["study_directions"] = list(directions.values())
        records["programs"] = programs

    def _curricula(
        self, university_id: str, source_items: list[Any], plugin: Any
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        curricula: list[dict[str, Any]] = []
        disciplines: list[dict[str, Any]] = []
        semesters: dict[int, dict[str, Any]] = {}
        semester_loads: list[dict[str, Any]] = []
        chain = build_resolver_chain(plugin.resolver_specs("total_hours"))
        for source in source_items:
            if not isinstance(source, SourceCurriculum):
                continue
            curricula.append(
                self.normalizer.curriculum(university_id, source).to_dict()
            )
            for index, row in enumerate(source.rows):
                name = str(row.get("discipline", "")).strip()
                if not name:
                    continue
                source_discipline = SourceDiscipline(
                    source_key=f"{source.source_key}:{name}:{index}",
                    name=name,
                    code=str(row.get("code", "") or ""),
                    credits=self._number(row.get("credits")),
                    components=row.get("components", {})
                    if isinstance(row.get("components", {}), dict)
                    else {},
                    semester=row.get("semester"),
                    raw=row,
                    provenance=source.provenance,
                )
                resolution = chain.resolve(
                    {
                        "total_hours": self._number(row.get("hours")),
                        "components": source_discipline.components,
                        "credits": source_discipline.credits,
                    }
                )
                canonical_discipline = self.normalizer.discipline(
                    university_id, source_discipline, resolution
                )
                disciplines.append(canonical_discipline.to_dict())
                semester = self._semester_number(source_discipline.semester)
                if semester is None:
                    continue
                semester_source = SourceSemester(
                    source_key=str(semester),
                    number=semester,
                    raw={"number": semester},
                    provenance=source.provenance,
                )
                semesters.setdefault(
                    semester,
                    self.normalizer.semester(university_id, semester_source).to_dict(),
                )
                load_source = SourceSemesterLoad(
                    source_key=f"{source_discipline.source_key}:{semester}",
                    discipline_key=source_discipline.source_key,
                    semester=semester,
                    hours=resolution.value,
                    credits=source_discipline.credits,
                    raw=row,
                    provenance=source.provenance,
                )
                semester_loads.append(
                    self.normalizer.semester_load(university_id, load_source).to_dict()
                )
        return curricula, disciplines, list(semesters.values()), semester_loads

    @staticmethod
    def _number(value: Any) -> int | float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value

    @staticmethod
    def _semester_number(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, float) and value.is_integer() and value > 0:
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            number = int(value.strip())
            return number if number > 0 else None
        return None
