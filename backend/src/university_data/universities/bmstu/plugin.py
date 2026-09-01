from __future__ import annotations

import csv
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ...core.capabilities import UniversityCapabilities
from ...core.config import ResolverSpec, load_plugin_config
from ...core.plugin import UniversityConfig, UniversityOperations, UniversityProviders
from ...core.source_models import (
    SourceAdmissionRequirement,
    SourceCurriculum,
    SourceDepartment,
    SourceFaculty,
    SourceProgram,
    SourceTuition,
)
from ...domain.ids import deterministic_source_keys
from ...domain.provenance import SourceProvenance
from ...runtime.atomic import atomic_text_writer, atomic_write_json
from ...sources.http import ApiClient
from .adapter.config import LIST_ENDPOINT, SOURCE_PAGE
from .adapter.domain.models import PlanFile, StudyPlan
from .adapter.ingestion.mirror_api import DetailFetch, MirrorApi
from .adapter.ingestion.yandex import StudyPlanResolver
from .adapter.study_plans.pipeline import StudyPlanExtractionPipeline
from .adapter.study_plans.semantic_source import source_rows_from_semantic
from .adapter.study_plans.semantics import enrich_existing_dataset
from .adapter.transform.normalize import Normalizer
from .adapter.transform.text import safe_filename

ROOT = Path(__file__).parent


def _provenance(value: Any, *, raw_path: str = "") -> SourceProvenance:
    source = getattr(value, "provenance", value)
    return SourceProvenance(
        source_page=str(getattr(source, "source_page", SOURCE_PAGE)),
        list_api=str(getattr(source, "list_api", LIST_ENDPOINT)),
        detail_api=str(getattr(source, "detail_api", "")),
        detail_page=str(getattr(source, "detail_page", "")),
        fetched_at_utc=str(getattr(source, "fetched_at_utc", "")),
        raw_snapshot_path=raw_path or str(getattr(source, "raw_snapshot_path", "")),
        source_key=str(getattr(source, "source_key", "")),
    )


def _key(value: Any, *fallbacks: Any) -> str:
    for candidate in (value, *fallbacks):
        text = str(candidate or "").strip()
        if text:
            return text
    return "unknown"


def _program_source_keys(major: Any) -> dict[str, str]:
    """Build reorder-stable keys shared by program and curriculum providers."""

    programs = list(major.educational_programs)
    direction_key = _key(major.slug, major.code, major.name)
    department_keys = {
        department.id: _key(department.slug, department.code, department.name)
        for department in major.departments
    }
    keys = deterministic_source_keys(
        programs,
        key=lambda program: (
            direction_key,
            program.code,
            program.name,
            department_keys.get(program.department_id, program.department_id),
        ),
    )
    return dict(zip((program.id for program in programs), keys, strict=True))


class BmstuSourceSnapshot:
    """One balanced source capture shared by all BMSTU capability providers."""

    def __init__(self, options: Any, *, replay_dir: Path | None = None) -> None:
        self.options = options
        self.output_dir = Path(options.output_dir) / "bmstu"
        self.replay_dir = replay_dir
        self._loaded = False
        self.summaries: list[dict[str, Any]] = []
        self.meta: dict[str, Any] = {}
        self.details: list[DetailFetch] = []
        self.majors: list[Any] = []

    def load(self) -> list[Any]:
        if self._loaded:
            return self.majors
        if self.replay_dir is not None:
            self._load_replay(self.replay_dir)
        else:
            client = ApiClient(
                timeout=float(self.options.timeout),
                delay=float(self.options.delay),
                user_agent="university-data-platform/bmstu-adapter",
            )
            api = MirrorApi(
                client,
                workers=int(self.options.workers),
                page_size=int(self.options.page_size),
            )
            self.summaries, self.meta = api.fetch_major_list()
            self.details = api.fetch_details(self.summaries)
        self._write_raw_snapshot()
        self.majors = [Normalizer().normalize(item) for item in self.details]
        if self.replay_dir is not None:
            self._restore_replay_plan_manifest()
        if bool(self.options.resolve_plans):
            client = ApiClient(
                timeout=float(self.options.timeout),
                delay=float(self.options.delay),
                user_agent="university-data-platform/bmstu-plan-resolver",
            )
            StudyPlanResolver(client, self.output_dir).enrich(
                self.majors,
                resolve=True,
                download=bool(self.options.download_plans),
            )
        self._write_plan_manifest()
        self._loaded = True
        return self.majors

    def _restore_replay_plan_manifest(self) -> None:
        """Attach existing downloaded documents without network resolution."""

        if self.replay_dir is not None:
            source_plans = self.replay_dir / "study_plans"
            target_plans = self.output_dir / "study_plans"
            if (
                source_plans.is_dir()
                and source_plans.resolve() != target_plans.resolve()
            ):
                shutil.copytree(source_plans, target_plans, dirs_exist_ok=True)
        manifest = self.replay_dir / "study_plan_files.csv" if self.replay_dir else None
        if manifest is None or not manifest.is_file():
            return
        rows: list[dict[str, str]] = []
        with manifest.open(encoding="utf-8-sig", newline="") as stream:
            rows.extend(dict(row) for row in csv.DictReader(stream))
        by_program: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            key = row.get("program_id", "")
            if key:
                by_program.setdefault(key, []).append(row)
        for major in self.majors:
            for program in major.educational_programs:
                program_rows = by_program.get(program.id, [])
                if not program_rows:
                    program_rows = [
                        row
                        for row in rows
                        if row.get("program_code") == program.code
                        and row.get("program_name") == program.name
                    ]
                if not program_rows:
                    continue
                files = [
                    PlanFile(
                        id=row.get("id", ""),
                        name=Path(row.get("local_path", "")).name,
                        path=row.get("local_path", ""),
                        size=(
                            int(row["size"]) if row.get("size", "").isdigit() else None
                        ),
                        mime_type=row.get("mime_type", ""),
                        md5="",
                        sha256=row.get("sha256", ""),
                        source_url=row.get("source_url", ""),
                        resolved_url=row.get("resolved_url", ""),
                        download_url=row.get("resolved_url", ""),
                        local_path=row.get("local_path", ""),
                        downloaded=True,
                        downloaded_size=(
                            int(row["size"]) if row.get("size", "").isdigit() else None
                        ),
                    )
                    for row in program_rows
                    if row.get("local_path")
                ]
                if files:
                    first = program_rows[0]
                    program.study_plan = StudyPlan(
                        url=first.get("plan_url", program.study_plan_url),
                        resolved_url=first.get("resolved_url", ""),
                        status=first.get("plan_status", "resolved"),
                        files=files,
                    )

    def plan_path(self, local_path: str) -> Path:
        return self.output_dir / Path(local_path.replace("\\", "/"))

    def _load_replay(self, source_dir: Path) -> None:
        payload = json.loads(
            (source_dir / "raw" / "majors_list.json").read_text(encoding="utf-8")
        )
        self.summaries = [
            item for item in payload.get("data", []) if isinstance(item, dict)
        ]
        self.meta = (
            dict(payload.get("meta", {}))
            if isinstance(payload.get("meta"), dict)
            else {}
        )
        self.details = []
        for path in sorted((source_dir / "raw" / "details").glob("*.json")):
            item = json.loads(path.read_text(encoding="utf-8"))
            self.details.append(
                DetailFetch(
                    item.get("summary", {}),
                    item.get("detail"),
                    item.get("error"),
                    item.get("fetched_at_utc", ""),
                )
            )

    def _write_raw_snapshot(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self.output_dir / "raw" / "majors_list.json",
            {"meta": self.meta, "data": self.summaries},
        )
        for fetched in self.details:
            slug = safe_filename(
                _key(fetched.summary.get("slug"), fetched.summary.get("code")),
                "major",
            )
            atomic_write_json(
                self.output_dir / "raw" / "details" / f"{slug}.json",
                {
                    "summary": fetched.summary,
                    "detail": fetched.detail,
                    "error": fetched.error,
                    "fetched_at_utc": fetched.fetched_at_utc,
                },
            )

    def _write_plan_manifest(self) -> None:
        fields = (
            "id",
            "local_path",
            "major_id",
            "major_slug",
            "major_code",
            "major_name",
            "program_id",
            "program_code",
            "program_name",
            "plan_url",
            "plan_status",
            "source_url",
            "resolved_url",
            "size",
            "sha256",
            "mime_type",
        )
        with atomic_text_writer(
            self.output_dir / "study_plan_files.csv", encoding="utf-8-sig", newline=""
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for major in self.majors:
                for program in major.educational_programs:
                    plan = program.study_plan
                    for file_info in plan.files:
                        writer.writerow(
                            {
                                "id": file_info.id,
                                "local_path": file_info.local_path,
                                "major_id": major.id,
                                "major_slug": major.slug,
                                "major_code": major.code,
                                "major_name": major.name,
                                "program_id": program.id,
                                "program_code": program.code,
                                "program_name": program.name,
                                "plan_url": plan.url,
                                "plan_status": plan.status,
                                "source_url": file_info.source_url,
                                "resolved_url": file_info.resolved_url,
                                "size": file_info.size,
                                "sha256": file_info.sha256,
                                "mime_type": file_info.mime_type,
                            }
                        )


class _BmstuProvider:
    def __init__(self, snapshot: BmstuSourceSnapshot) -> None:
        self.snapshot = snapshot

    @property
    def majors(self) -> list[Any]:
        return self.snapshot.load()


class BmstuProgramsProvider(_BmstuProvider):
    capability = "programs"

    def fetch(self) -> list[SourceProgram]:
        result: list[SourceProgram] = []
        for major in self.majors:
            direction_key = _key(major.slug, major.code, major.name)
            department_keys = {
                department.id: _key(department.slug, department.code, department.name)
                for department in major.departments
            }
            program_keys = _program_source_keys(major)
            for program in major.educational_programs:
                result.append(
                    SourceProgram(
                        source_key=program_keys[program.id],
                        name=program.name,
                        code=program.code,
                        study_direction_key=direction_key,
                        department_key=department_keys.get(
                            program.department_id, program.department_id
                        ),
                        description=program.description,
                        study_plan_url=program.study_plan_url,
                        raw={
                            "study_direction_name": major.name,
                            "study_direction_code": major.code,
                            "major_id": major.id,
                            "program_id": program.id,
                        },
                        provenance=_provenance(
                            program, raw_path=major.provenance.raw_snapshot_path
                        ),
                    )
                )
        return result


class BmstuFacultiesProvider(_BmstuProvider):
    capability = "faculties"

    def fetch(self) -> list[SourceFaculty]:
        result: dict[str, SourceFaculty] = {}
        for major in self.majors:
            for faculty in major.faculties:
                key = _key(faculty.slug, faculty.code, faculty.name)
                result.setdefault(
                    key,
                    SourceFaculty(
                        source_key=key,
                        name=faculty.name,
                        code=faculty.code,
                        raw=asdict(faculty),
                        provenance=_provenance(faculty),
                    ),
                )
        return list(result.values())


class BmstuDepartmentsProvider(_BmstuProvider):
    capability = "departments"

    def fetch(self) -> list[SourceDepartment]:
        result: dict[str, SourceDepartment] = {}
        for major in self.majors:
            faculty_keys = {
                faculty.id: _key(faculty.slug, faculty.code, faculty.name)
                for faculty in major.faculties
            }
            for department in major.departments:
                key = _key(department.slug, department.code, department.name)
                result.setdefault(
                    key,
                    SourceDepartment(
                        source_key=key,
                        name=department.name,
                        code=department.code,
                        faculty_key=faculty_keys.get(
                            department.faculty_id, department.faculty_id
                        ),
                        raw=asdict(department),
                        provenance=_provenance(department),
                    ),
                )
        return list(result.values())


class BmstuAdmissionProvider(_BmstuProvider):
    capability = "admission"

    def fetch(self) -> list[SourceAdmissionRequirement]:
        result: list[SourceAdmissionRequirement] = []
        for major in self.majors:
            direction_key = _key(major.slug, major.code, major.name)
            for requirement in major.entrance_requirements:
                result.append(
                    SourceAdmissionRequirement(
                        source_key=f"{direction_key}:{requirement.subject}:{requirement.id}",
                        subject=requirement.subject,
                        minimum_score=requirement.minimum_score,
                        is_choice=requirement.is_choice,
                        study_direction_key=direction_key,
                        raw=asdict(requirement),
                        provenance=_provenance(requirement),
                    )
                )
        return result


class BmstuTuitionProvider(_BmstuProvider):
    capability = "tuition"

    def fetch(self) -> list[SourceTuition]:
        result: list[SourceTuition] = []
        for major in self.majors:
            direction_key = _key(major.slug, major.code, major.name)
            for option in major.tuition:
                result.append(
                    SourceTuition(
                        source_key=(
                            f"{direction_key}:{option.study_form}:"
                            f"{option.term}:{option.id}"
                        ),
                        study_form=option.study_form,
                        value=str(option.value) if option.value is not None else None,
                        currency=option.currency,
                        term=option.term,
                        study_direction_key=direction_key,
                        raw=asdict(option),
                        provenance=_provenance(option),
                    )
                )
        return result


class BmstuCurriculaProvider(_BmstuProvider):
    capability = "curricula"

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        values: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    values.append(value)
        return values

    @staticmethod
    def _number(value: Any) -> int | float | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return int(number) if number.is_integer() else number

    @classmethod
    def _read_semantic_loads(cls, path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        numeric_fields = {
            "semester",
            "weeks",
            "credits",
            "hours",
            "audited_hours",
            "independent_or_other_hours",
        }
        json_fields = {
            "control_tokens",
            "control_kinds",
            "raw",
            "raw_bands",
            "normalization_notes",
            "source_cell_ids",
            "source_word_ids",
        }
        loads: list[dict[str, Any]] = []
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for source in csv.DictReader(stream):
                load: dict[str, Any] = dict(source)
                for field in numeric_fields:
                    load[field] = cls._number(load.get(field))
                for field in json_fields:
                    value = load.get(field, "")
                    if not value:
                        load[field] = [] if field.endswith("s") else {}
                        continue
                    try:
                        load[field] = json.loads(value)
                    except json.JSONDecodeError:
                        load[field] = [] if field.endswith("s") else {}
                loads.append(load)
        return loads

    def _semantic_dataset(
        self,
    ) -> tuple[
        dict[str, list[dict[str, Any]]],
        dict[str, Any],
        dict[str, Any],
    ]:
        """Run the balanced document/semantic stages once per source snapshot."""

        result_dir = self.snapshot.output_dir
        manifest = result_dir / "study_plan_files.csv"
        if not manifest.is_file():
            return (
                {},
                {"verification": {"passed": True}},
                {"verification": {"passed": True}},
            )
        with manifest.open(encoding="utf-8-sig", newline="") as stream:
            if not any(row.get("local_path") for row in csv.DictReader(stream)):
                return (
                    {},
                    {"verification": {"passed": True}},
                    {"verification": {"passed": True}},
                )
        extraction_report = StudyPlanExtractionPipeline(
            result_dir,
            workers=int(self.snapshot.options.workers),
            reader_backend=self.snapshot.options.reader_backend,
            resume=True,
        ).run()
        semantic_report = enrich_existing_dataset(result_dir)
        disciplines = self._read_jsonl(
            result_dir / "study_plan_data/study_plan_disciplines.jsonl"
        )
        loads = self._read_semantic_loads(
            result_dir / "study_plan_data/study_plan_semester_load.csv"
        )
        loads_by_discipline: dict[str, list[dict[str, Any]]] = {}
        for load in loads:
            discipline_id = str(load.get("discipline_id", ""))
            if discipline_id:
                loads_by_discipline.setdefault(discipline_id, []).append(load)
        rows_by_document: dict[str, list[dict[str, Any]]] = {}
        for discipline in disciplines:
            document_id = str(discipline.get("document_id", ""))
            if not document_id:
                continue
            discipline_id = str(discipline.get("id", ""))
            rows_by_document.setdefault(document_id, []).extend(
                source_rows_from_semantic(
                    {
                        "disciplines": [discipline],
                        "semester_loads": loads_by_discipline.get(discipline_id, []),
                    }
                )
            )
        return rows_by_document, semantic_report, extraction_report

    def fetch(self) -> list[SourceCurriculum]:
        programs: list[tuple[Any, str]] = []
        for major in self.majors:
            program_keys = _program_source_keys(major)
            for program in major.educational_programs:
                program_key = program_keys[program.id]
                programs.append((program, program_key))
        rows_by_document, semantic_report, extraction_report = self._semantic_dataset()
        extraction_ok = bool(extraction_report.get("verification", {}).get("passed"))
        semantic_ok = bool(semantic_report.get("verification", {}).get("passed"))
        stage_warnings: list[str] = []
        if not extraction_ok:
            stage_warnings.append("study-plan extraction quality gate failed")
        if not semantic_ok:
            stage_warnings.append("study-plan semantic quality gate failed")

        result: list[SourceCurriculum] = []
        for program, program_key in programs:
            plan = program.study_plan
            parsed_rows: list[dict[str, Any]] = []
            semantic_reports: list[dict[str, Any]] = []
            semantic_documents: list[str] = []
            parse_warnings = list(stage_warnings)
            for file_info in plan.files:
                if not file_info.local_path:
                    continue
                parsed_rows.extend(rows_by_document.get(file_info.id, []))
                if file_info.id in rows_by_document:
                    semantic_documents.append(file_info.id)
            if plan.files:
                semantic_reports.append(semantic_report)
            result.append(
                SourceCurriculum(
                    source_key=f"{program_key}:curriculum",
                    name=program.name,
                    program_key=program_key,
                    path=(
                        self.snapshot.plan_path(plan.files[0].local_path)
                        if plan.files and plan.files[0].local_path
                        else None
                    ),
                    rows=tuple(parsed_rows),
                    raw={
                        "program_id": program.id,
                        "plan_status": plan.status,
                        "plan_url": plan.url,
                        "files": [asdict(item) for item in plan.files],
                        "semantic_reports": semantic_reports,
                        "semantic_warnings": parse_warnings,
                    },
                    provenance=_provenance(program),
                    extensions={
                        "study_plan_status": plan.status,
                        "study_plan_file_count": len(plan.files),
                        "semantic_documents": semantic_documents,
                        "semantic_reports": semantic_reports,
                        "semantic_warnings": parse_warnings,
                        "extraction_report": extraction_report,
                    },
                )
            )
        return result


class BmstuOperations:
    def execute(self, request: Any, result_dir: Path) -> dict[str, Any]:
        if request.operation not in {
            "extract_study_plans",
            "extract_semantics",
            "compact_study_plans",
        }:
            raise ValueError(f"Unsupported BMSTU operation: {request.operation}")
        from ...core.registry import UniversityRegistry
        from ...pipeline import PipelineOptions, UniversityPipeline

        # Replaying the namespaced raw snapshot makes every PDF operation use
        # the same Source DTO → canonical → ontology seam as a refresh.
        plugin = BmstuPlugin(replay_dir=result_dir)
        return UniversityPipeline(UniversityRegistry((plugin,))).run(
            "bmstu",
            PipelineOptions(
                output_dir=result_dir.parent,
                workers=request.workers,
                timeout=request.timeout,
                delay=request.delay,
                resolve_plans=False,
                download_plans=False,
                reader_backend=request.reader_backend,
                strict=False,
            ),
        )


class BmstuPlugin:
    university_id = "bmstu"
    display_name = "МГТУ им. Н. Э. Баумана"

    def __init__(self, *, replay_dir: Path | None = None) -> None:
        self.replay_dir = replay_dir

    def capabilities(self) -> UniversityCapabilities:
        config = load_plugin_config(ROOT / "config.yaml")
        return UniversityCapabilities(**config.capabilities)

    def providers(self, options: Any | None = None) -> UniversityProviders:
        if options is None:
            from ...pipeline import PipelineOptions

            options = PipelineOptions()
        snapshot = BmstuSourceSnapshot(options, replay_dir=self.replay_dir)
        return UniversityProviders(
            programs=BmstuProgramsProvider(snapshot),
            curricula=BmstuCurriculaProvider(snapshot),
            faculties=BmstuFacultiesProvider(snapshot),
            departments=BmstuDepartmentsProvider(snapshot),
            admission=BmstuAdmissionProvider(snapshot),
            tuition=BmstuTuitionProvider(snapshot),
        )

    def resolver_specs(self, field: str) -> tuple[ResolverSpec, ...]:
        config = load_plugin_config(ROOT / "config.yaml")
        return config.resolvers.get(field, ())

    def operations(self) -> UniversityOperations:
        return BmstuOperations()

    def config(self) -> UniversityConfig:
        config = load_plugin_config(ROOT / "config.yaml")
        return UniversityConfig(
            university_id=config.university_id,
            display_name=config.display_name,
            config_path=ROOT / "config.yaml",
            settings=config.settings,
        )
