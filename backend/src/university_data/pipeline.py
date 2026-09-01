from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from .core.capability_registry import CORE_CAPABILITY_DEFINITIONS, capability_definition
from .core.contracts import ProviderContractError, validate_provider_result
from .core.plugin import (
    manifest_for_plugin,
    resolver_builders_for,
    resolver_specs_for,
)
from .core.registry import UniversityRegistry
from .core.source_models import SourceDiscipline, SourceSemester, SourceSemesterLoad
from .domain.aliases import build_id_aliases
from .domain.ids import deterministic_source_keys
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
    reader_backend: str = "native"
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
        manifest = manifest_for_plugin(plugin)
        university_id = manifest.university_id
        output_root = options.output_dir.resolve()
        pipeline_run = PipelineRun(output_root / university_id, "university_pipeline")
        final_storage = UniversityStorage(output_root, university_id)
        candidate = final_storage.candidate(pipeline_run.run_id)
        candidate.ensure()
        candidate_options = replace(options, output_dir=candidate.root)
        published = False
        finished = False

        try:
            quality = self._run_candidate(
                university_id,
                candidate_options,
                plugin,
                manifest,
                candidate,
                pipeline_run,
                final_storage,
            )
            passed = bool(quality["verification"]["passed"])
            if passed:
                final_storage.publish(candidate, pipeline_run.run_id)
                published = True
                pipeline_run.finish(status="succeeded", quality=quality)
            else:
                pipeline_run.finish(status="failed", quality=quality)
            finished = True
            if options.strict and not passed:
                raise RuntimeError(f"Quality gate failed for {university_id}")
            return quality
        except Exception as exc:
            if not finished:
                pipeline_run.finish(
                    status="failed", error=f"{type(exc).__name__}: {exc}"
                )
            raise
        finally:
            if not published:
                candidate.discard()

    def _run_candidate(
        self,
        university_id: str,
        options: PipelineOptions,
        plugin: Any,
        manifest: Any,
        storage: UniversityStorage,
        pipeline_run: PipelineRun,
        previous_storage: UniversityStorage,
    ) -> dict[str, Any]:
        capability_specs = manifest.capability_specs()
        capabilities = manifest.capabilities_dict()
        available_datasets = {"universities"}
        for spec in capability_specs:
            if spec.enabled:
                available_datasets.update(
                    CORE_CAPABILITY_DEFINITIONS[spec.name].datasets
                )
        providers = plugin.providers(options)
        records: dict[str, list[dict[str, Any]]] = {
            "universities": [
                self.normalizer.university(
                    university_id,
                    manifest.display_name,
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
        capability_states: dict[str, str] = {}
        capability_warnings: dict[str, list[str]] = {}
        capability_gaps: dict[str, list[dict[str, str]]] = {}
        capability_metrics: dict[str, dict[str, Any]] = {}

        for spec in capability_specs:
            capability = spec.name
            if not spec.enabled:
                capability_states[capability] = "not_supported"
                capability_metrics[capability] = {
                    "status": "not_supported",
                    "records": 0,
                    "warnings": 0,
                    "gaps": 0,
                    "failures": 0,
                    "duration_ms": 0.0,
                }
                continue
            provider_lookup = getattr(providers, "for_capability", None)
            provider = (
                provider_lookup(capability)
                if callable(provider_lookup)
                else providers.get(capability)
            )
            if provider is None:
                raise ProviderContractError(
                    f"capability {capability!r} is declared but provider is missing"
                )
            started = perf_counter()
            records_count = 0
            warnings_count = 0
            gaps_count = 0
            try:
                provider_result = validate_provider_result(
                    capability, provider, provider.fetch()
                )
                records_count = len(provider_result.records)
                warnings_count = len(provider_result.warnings)
                gaps_count = len(provider_result.gaps)
                if not provider_result.complete and not spec.allow_partial:
                    capability_states[capability] = "failed"
                    errors.append(
                        f"{capability}: provider returned partial data but the module "
                        "does not allow partial publication"
                    )
                    continue
                source_items = list(provider_result.records)
                capability_states[capability] = (
                    "published" if provider_result.complete else "degraded"
                )
                if provider_result.warnings:
                    capability_warnings[capability] = list(provider_result.warnings)
                if provider_result.gaps:
                    capability_gaps[capability] = [
                        {
                            "code": gap.code,
                            "message": gap.message,
                            "source_key": gap.source_key,
                        }
                        for gap in provider_result.gaps
                    ]
                self._materialize_capability(
                    university_id,
                    capability,
                    source_items,
                    plugin,
                    records,
                    capabilities,
                )
            except ProviderContractError:
                raise
            except Exception as exc:  # noqa: BLE001
                capability_states[capability] = "failed"
                errors.append(f"{capability}: {type(exc).__name__}: {exc}")
            finally:
                capability_status = capability_states.get(capability, "failed")
                capability_metrics[capability] = {
                    "status": capability_status,
                    "records": records_count,
                    "warnings": warnings_count,
                    "gaps": gaps_count,
                    "failures": int(capability_status == "failed"),
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                }

        ontology = build_ontology(
            university_id,
            records,
            capabilities=capabilities,
        )
        quality = build_quality_report(
            university_id,
            capability_specs,
            records,
            errors=errors,
            ontology=ontology,
            capability_states=capability_states,
            capability_warnings=capability_warnings,
            capability_gaps=capability_gaps,
            capability_metrics=capability_metrics,
            module_version=manifest.module_version,
            module_config_hash=manifest.config_hash(),
            active_snapshot=pipeline_run.run_id,
        )
        aliases = build_id_aliases(
            previous_storage.read_canonical_records(),
            records,
            existing=previous_storage.read_aliases(),
        )
        storage.ensure()
        storage.write_json(
            "canonical/catalog.json",
            {
                "university_id": university_id,
                "records": {
                    name: items
                    for name, items in records.items()
                    if name in available_datasets
                },
                "quality": quality,
                "generated_at_utc": _now(),
            },
        )
        storage.write_json("ontology.json", ontology)
        storage.write_json("quality/report.json", quality)
        storage.write_json(
            "id_aliases.json",
            {
                "schema_version": "1.0",
                "university_id": university_id,
                "aliases": aliases,
            },
        )
        semantic_rows = [
            item
            for item in records["disciplines"]
            if isinstance(item.get("extensions"), dict)
            and any(
                isinstance(value, dict) and "semantic_source_id" in value
                for value in item["extensions"].values()
            )
        ]
        semantic_loads = [
            item
            for item in records["semester_loads"]
            if isinstance(item.get("extensions"), dict)
            and any(
                isinstance(value, dict) and "semantic_source_id" in value
                for value in item["extensions"].values()
            )
        ]
        if capabilities.get("curricula", False):
            storage.write_jsonl("semantic/study_plan_disciplines.jsonl", semantic_rows)
            storage.write_jsonl(
                "semantic/study_plan_semester_loads.jsonl", semantic_loads
            )
            storage.write_json(
                "semantic/reports.json",
                {
                    "curricula": [
                        {
                            "curriculum_id": item.get("id", ""),
                            "extensions": item.get("extensions", {}),
                        }
                        for item in records["curricula"]
                        if item.get("extensions")
                    ],
                    "counts": {
                        "disciplines": len(semantic_rows),
                        "semester_loads": len(semantic_loads),
                    },
                },
            )
        for name, items in records.items():
            if name not in available_datasets:
                continue
            storage.write_jsonl(f"canonical/{name}.jsonl", items)
            storage.write_csv(f"canonical/{name}.csv", items)
        pipeline_run.stage(
            "source_ingestion",
            inputs=["raw"],
            outputs=["raw"],
            metadata={
                "capabilities": capabilities,
                "module_version": manifest.module_version,
                "module_config_hash": manifest.config_hash(),
                "capability_metrics": capability_metrics,
            },
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
        return quality

    def _materialize_capability(
        self,
        university_id: str,
        capability: str,
        source_items: list[Any],
        plugin: Any,
        records: dict[str, list[dict[str, Any]]],
        capabilities: dict[str, bool],
    ) -> None:
        definition = capability_definition(capability)
        if capability == "curricula":
            curricula, disciplines, semesters, loads = self._curricula(
                university_id, source_items, plugin, capabilities
            )
            records["curricula"] = curricula
            records["disciplines"] = disciplines
            records["semesters"] = semesters
            records["semester_loads"] = loads
            return
        materializer = getattr(self, definition.materializer)
        materialized = materializer(university_id, source_items, records, capabilities)
        if materialized is not None:
            records[definition.primary_dataset] = materialized

    def _faculties(
        self,
        university_id: str,
        source_items: list[Any],
        _records: dict[str, list[dict[str, Any]]],
        _capabilities: dict[str, bool],
    ) -> list[dict[str, Any]]:
        return [
            self.normalizer.faculty(university_id, item).to_dict()
            for item in source_items
        ]

    def _departments(
        self,
        university_id: str,
        source_items: list[Any],
        _records: dict[str, list[dict[str, Any]]],
        capabilities: dict[str, bool],
    ) -> list[dict[str, Any]]:
        return [
            self.normalizer.department(
                university_id, item, available_capabilities=capabilities
            ).to_dict()
            for item in source_items
        ]

    def _teachers(
        self,
        university_id: str,
        source_items: list[Any],
        _records: dict[str, list[dict[str, Any]]],
        capabilities: dict[str, bool],
    ) -> list[dict[str, Any]]:
        return [
            self.normalizer.teacher(
                university_id, item, available_capabilities=capabilities
            ).to_dict()
            for item in source_items
        ]

    def _admission(
        self,
        university_id: str,
        source_items: list[Any],
        _records: dict[str, list[dict[str, Any]]],
        capabilities: dict[str, bool],
    ) -> list[dict[str, Any]]:
        return [
            self.normalizer.admission(
                university_id, item, available_capabilities=capabilities
            ).to_dict()
            for item in source_items
        ]

    def _tuition(
        self,
        university_id: str,
        source_items: list[Any],
        _records: dict[str, list[dict[str, Any]]],
        capabilities: dict[str, bool],
    ) -> list[dict[str, Any]]:
        return [
            self.normalizer.tuition(
                university_id, item, available_capabilities=capabilities
            ).to_dict()
            for item in source_items
        ]

    def _programs(
        self,
        university_id: str,
        source_items: list[Any],
        records: dict[str, list[dict[str, Any]]],
        capabilities: dict[str, bool],
    ) -> None:
        programs: list[dict[str, Any]] = []
        directions: dict[str, dict[str, Any]] = {}
        for item in source_items:
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
            programs.append(
                self.normalizer.program(
                    university_id,
                    item,
                    available_capabilities=capabilities,
                ).to_dict()
            )
        records["study_directions"] = list(directions.values())
        records["programs"] = programs

    def _curricula(
        self,
        university_id: str,
        source_items: list[Any],
        plugin: Any,
        capabilities: dict[str, bool],
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
        custom_builders = resolver_builders_for(plugin, "total_hours")
        chain = build_resolver_chain(
            resolver_specs_for(plugin, "total_hours"), custom=custom_builders
        )
        for source in source_items:
            curricula.append(
                self.normalizer.curriculum(
                    university_id,
                    source,
                    available_capabilities=capabilities,
                ).to_dict()
            )
            rows = [
                row
                for row in source.rows
                if isinstance(row, dict)
                and str(row.get("discipline", row.get("name", ""))).strip()
            ]
            source_keys = deterministic_source_keys(
                rows,
                key=lambda row: (
                    source.source_key,
                    row.get("code", ""),
                    row.get("discipline", row.get("name", "")),
                    row.get("department", ""),
                    row.get("section_path", ""),
                ),
            )
            for row, discipline_source_key in zip(rows, source_keys, strict=True):
                name = str(row.get("discipline", "")).strip()
                if not name:
                    name = str(row.get("name", "")).strip()
                components = row.get("components", {})
                if not isinstance(components, dict):
                    components = {}
                source_discipline = SourceDiscipline(
                    source_key=f"{source.source_key}:discipline:{discipline_source_key}",
                    name=name,
                    code=str(row.get("code", "") or ""),
                    curriculum_key=source.source_key,
                    total_hours=self._number(row.get("total_hours", row.get("hours"))),
                    credits=self._number(row.get("credits")),
                    components=components,
                    semester=row.get("semester"),
                    raw=row,
                    provenance=source.provenance,
                    extensions=(
                        dict(row.get("extensions", {}))
                        if isinstance(row.get("extensions"), dict)
                        else {}
                    ),
                )
                resolution = self._resolve_hours(chain, source_discipline, row)
                canonical_discipline = self.normalizer.discipline(
                    university_id,
                    source_discipline,
                    resolution,
                    available_capabilities=capabilities,
                )
                disciplines.append(canonical_discipline.to_dict())
                raw_loads = row.get("semester_loads")
                load_rows = (
                    [item for item in raw_loads if isinstance(item, dict)]
                    if isinstance(raw_loads, list)
                    else []
                )
                if not load_rows:
                    load_rows = [row]
                for load_row in load_rows:
                    semester = self._semester_number(load_row.get("semester"))
                    if semester is None:
                        continue
                    load_components = load_row.get("components", components)
                    if not isinstance(load_components, dict):
                        load_components = components
                    load_resolution = chain.resolve(
                        {
                            "total_hours": self._number(
                                load_row.get("total_hours", load_row.get("hours"))
                            ),
                            "components": load_components,
                            "credits": self._number(load_row.get("credits")),
                        }
                    )
                    semester_source = SourceSemester(
                        source_key=str(semester),
                        number=semester,
                        raw={"number": semester},
                        provenance=source.provenance,
                    )
                    semesters.setdefault(
                        semester,
                        self.normalizer.semester(
                            university_id, semester_source
                        ).to_dict(),
                    )
                    load_source = SourceSemesterLoad(
                        source_key=f"{source_discipline.source_key}:semester:{semester}",
                        discipline_key=source_discipline.source_key,
                        curriculum_key=source.source_key,
                        semester=semester,
                        hours=load_resolution.value,
                        credits=self._number(load_row.get("credits")),
                        raw=load_row,
                        provenance=source.provenance,
                        extensions=(
                            dict(load_row.get("extensions", {}))
                            if isinstance(load_row.get("extensions"), dict)
                            else {}
                        ),
                    )
                    semester_loads.append(
                        self.normalizer.semester_load(
                            university_id,
                            load_source,
                            available_capabilities=capabilities,
                        ).to_dict()
                    )
        return curricula, disciplines, list(semesters.values()), semester_loads

    @staticmethod
    def _resolve_hours(
        chain: Any, source: SourceDiscipline, row: dict[str, Any]
    ) -> Any:
        return chain.resolve(
            {
                "total_hours": source.total_hours,
                "components": source.components,
                "credits": source.credits,
                "raw": row,
            }
        )

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
