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
    SourceFaculty,
    SourceProgram,
    SourceTeacher,
    SourceTuition,
)
from .domain.ids import global_stable_id
from .domain.provenance import FieldMeta
from .normalization import CanonicalNormalizer
from .ontology import build_ontology
from .quality import build_quality_report
from .resolvers import (
    CreditsToHoursResolver,
    DirectValueResolver,
    Resolver,
    ResolverChain,
    SumHourComponentsResolver,
)
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
    """University-neutral orchestration seam.

    Providers produce DTOs; only this module materializes canonical records.
    A plugin may expose an optional ``run_legacy`` seam for a source whose
    mature pipeline already owns specialized ingestion behavior.
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
        legacy_runner = getattr(plugin, "run_legacy", None)
        if callable(legacy_runner):
            return legacy_runner(options)

        capabilities = plugin.capabilities()
        providers = plugin.providers()
        records: dict[str, list[dict[str, Any]]] = {
            "faculties": [],
            "departments": [],
            "study_directions": [],
            "programs": [],
            "curricula": [],
            "teachers": [],
            "admission_requirements": [],
            "tuition_options": [],
            "disciplines": [],
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
            except Exception as exc:  # noqa: BLE001  # provider boundary is reported by quality
                errors.append(f"{capability}: {type(exc).__name__}: {exc}")
                continue
            if capability == "faculties":
                records["faculties"] = [
                    self._faculty(university_id, item)
                    for item in source_items
                    if isinstance(item, SourceFaculty)
                ]
            elif capability == "departments":
                records["departments"] = [
                    self._department(university_id, item)
                    for item in source_items
                    if isinstance(item, SourceDepartment)
                ]
            elif capability == "programs":
                programs = []
                directions: dict[str, dict[str, Any]] = {}
                for item in source_items:
                    if not isinstance(item, SourceProgram):
                        continue
                    direction_key = item.study_direction_key or item.code or item.name
                    direction_id = global_stable_id(
                        university_id, "study_direction", direction_key
                    )
                    directions.setdefault(
                        direction_key,
                        {
                            "id": direction_id,
                            "university_id": university_id,
                            "name": direction_key,
                            "code": direction_key,
                            "field_meta": {
                                "name": FieldMeta(
                                    "derived", "source_key", 0.5
                                ).to_dict()
                            },
                            "extensions": {},
                            "provenance": item.provenance.to_dict(),
                        },
                    )
                    programs.append(self.normalizer.program(university_id, item))
                records["study_directions"] = list(directions.values())
                records["programs"] = programs
            elif capability == "teachers":
                teachers = []
                for item in source_items:
                    if not isinstance(item, SourceTeacher):
                        continue
                    row = self.normalizer.teacher(university_id, item)
                    raw = item.raw
                    if "teacher_rating" in raw:
                        row["extensions"] = {
                            "fake": {"teacher_rating": raw["teacher_rating"]}
                        }
                    teachers.append(row)
                records["teachers"] = teachers
            elif capability == "admission":
                records["admission_requirements"] = [
                    self._admission(university_id, item)
                    for item in source_items
                    if isinstance(item, SourceAdmissionRequirement)
                ]
            elif capability == "tuition":
                records["tuition_options"] = [
                    self._tuition(university_id, item)
                    for item in source_items
                    if isinstance(item, SourceTuition)
                ]
            elif capability == "curricula":
                records["curricula"], records["disciplines"] = self._curricula(
                    university_id, source_items, plugin
                )

        ontology = build_ontology(university_id, records)
        quality = build_quality_report(
            university_id, capabilities.as_dict(), records, errors=errors
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
        storage.write_json(
            "pipeline_runs/latest.json",
            {
                "status": "succeeded"
                if quality["verification"]["passed"]
                else "failed",
                "university_id": university_id,
                "quality": quality,
                "finished_at_utc": _now(),
            },
        )
        if options.strict and not quality["verification"]["passed"]:
            raise RuntimeError(f"Quality gate failed for {university_id}")
        return quality

    def _admission(
        self, university_id: str, source: SourceAdmissionRequirement
    ) -> dict[str, Any]:
        program_key = source.raw.get("program", "")
        program_id = global_stable_id(university_id, "program", program_key)
        identifier = global_stable_id(
            university_id, "admission_requirement", source.source_key or source.subject
        )
        return {
            "id": identifier,
            "university_id": university_id,
            "program_id": program_id,
            "subject": source.subject,
            "minimum_score": source.minimum_score,
            "is_choice": source.is_choice,
            "field_meta": {
                "minimum_score": FieldMeta(
                    "published"
                    if source.minimum_score is not None
                    else "not_published",
                    "source",
                    1.0 if source.minimum_score is not None else 0.0,
                ).to_dict()
            },
            "extensions": {},
            "provenance": source.provenance.to_dict(),
        }

    def _faculty(self, university_id: str, source: SourceFaculty) -> dict[str, Any]:
        identifier = global_stable_id(
            university_id, "faculty", source.source_key or source.code or source.name
        )
        return {
            "id": identifier,
            "university_id": university_id,
            "name": source.name,
            "code": source.code,
            "field_meta": {
                "name": FieldMeta("published", "source", 1.0).to_dict(),
                "code": FieldMeta(
                    "published" if source.code else "not_published",
                    "source",
                    1.0 if source.code else 0.0,
                ).to_dict(),
            },
            "extensions": {},
            "provenance": source.provenance.to_dict(),
        }

    def _department(
        self, university_id: str, source: SourceDepartment
    ) -> dict[str, Any]:
        identifier = global_stable_id(
            university_id, "department", source.source_key or source.code or source.name
        )
        return {
            "id": identifier,
            "university_id": university_id,
            "name": source.name,
            "code": source.code,
            "faculty_id": (
                global_stable_id(university_id, "faculty", source.faculty_key)
                if source.faculty_key
                else ""
            ),
            "field_meta": {
                "name": FieldMeta("published", "source", 1.0).to_dict(),
                "code": FieldMeta(
                    "published" if source.code else "not_published",
                    "source",
                    1.0 if source.code else 0.0,
                ).to_dict(),
            },
            "extensions": {},
            "provenance": source.provenance.to_dict(),
        }

    def _tuition(self, university_id: str, source: SourceTuition) -> dict[str, Any]:
        program_key = str(source.raw.get("program", ""))
        return {
            "id": global_stable_id(
                university_id,
                "tuition_option",
                source.source_key or source.study_form,
            ),
            "university_id": university_id,
            "program_id": (
                global_stable_id(university_id, "program", program_key)
                if program_key
                else ""
            ),
            "study_form": source.study_form,
            "value": source.value,
            "currency": source.currency,
            "term": source.term,
            "field_meta": {
                "value": FieldMeta(
                    "published" if source.value is not None else "not_published",
                    "source",
                    1.0 if source.value is not None else 0.0,
                ).to_dict()
            },
            "extensions": {},
            "provenance": source.provenance.to_dict(),
        }

    def _curricula(
        self, university_id: str, source_items: list[Any], plugin: Any
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        curricula: list[dict[str, Any]] = []
        disciplines: list[dict[str, Any]] = []
        resolver_names = getattr(
            plugin, "resolver_names", lambda _field: ("direct", "sum_components")
        )("total_hours")
        resolver_map: dict[str, Resolver[int | float]] = {
            "direct": DirectValueResolver(),
            "sum_components": SumHourComponentsResolver(),
            "credits_to_hours": CreditsToHoursResolver(),
        }
        chain: ResolverChain[int | float] = ResolverChain(
            [resolver_map[name] for name in resolver_names if name in resolver_map]
        )
        for source in source_items:
            if not isinstance(source, SourceCurriculum):
                continue
            curriculum_id = global_stable_id(
                university_id, "curriculum", source.source_key
            )
            program_id = global_stable_id(university_id, "program", source.program_key)
            curricula.append(
                {
                    "id": curriculum_id,
                    "university_id": university_id,
                    "program_id": program_id,
                    "name": source.name,
                    "source_path": str(source.path or ""),
                    "field_meta": {
                        "name": FieldMeta("published", "source", 1.0).to_dict()
                    },
                    "extensions": {},
                    "provenance": source.provenance.to_dict(),
                }
            )
            for row in source.rows:
                name = str(row.get("discipline", "")).strip()
                if not name:
                    continue
                source_values = {
                    "total_hours": row.get("hours"),
                    "components": row.get("components", {}),
                    "credits": row.get("credits"),
                }
                resolution = chain.resolve(source_values)
                discipline_id = global_stable_id(university_id, "discipline", name)
                disciplines.append(
                    {
                        "id": discipline_id,
                        "university_id": university_id,
                        "name": name,
                        "code": str(row.get("code", "") or ""),
                        "total_hours": resolution.value,
                        "credits": row.get("credits"),
                        "semester": row.get("semester"),
                        "field_meta": {
                            "total_hours": {
                                "status": resolution.status,
                                "method": resolution.method,
                                "confidence": resolution.confidence,
                                "sources": resolution.sources,
                                "warnings": resolution.warnings,
                            }
                        },
                        "extensions": {},
                        "provenance": source.provenance.to_dict(),
                    }
                )
        return curricula, disciplines
