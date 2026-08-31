from __future__ import annotations

import csv
import json
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
from ...domain.provenance import SourceProvenance
from ...runtime.atomic import atomic_text_writer, atomic_write_json
from ...sources.http import ApiClient
from .adapter.config import LIST_ENDPOINT, SOURCE_PAGE
from .adapter.ingestion.mirror_api import DetailFetch, MirrorApi
from .adapter.ingestion.yandex import StudyPlanResolver
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
            for program in major.educational_programs:
                result.append(
                    SourceProgram(
                        source_key=_key(program.code, program.name, program.id),
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
                        source_key=f"{direction_key}:{option.study_form}:{option.term}",
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

    def fetch(self) -> list[SourceCurriculum]:
        result: list[SourceCurriculum] = []
        for major in self.majors:
            for program in major.educational_programs:
                plan = program.study_plan
                first_file = plan.files[0] if plan.files else None
                result.append(
                    SourceCurriculum(
                        source_key=f"{_key(program.code, program.name, program.id)}:curriculum",
                        name=program.name,
                        program_key=_key(program.code, program.name, program.id),
                        path=(
                            Path(first_file.local_path)
                            if first_file and first_file.local_path
                            else None
                        ),
                        raw={
                            "program_id": program.id,
                            "plan_status": plan.status,
                            "plan_url": plan.url,
                            "files": [asdict(item) for item in plan.files],
                        },
                        provenance=_provenance(program),
                        extensions={
                            "study_plan_status": plan.status,
                            "study_plan_file_count": len(plan.files),
                        },
                    )
                )
        return result


class BmstuOperations:
    def execute(self, request: Any, result_dir: Path) -> dict[str, Any]:
        operation = request.operation
        if operation == "extract_study_plans":
            from .adapter.study_plans.pipeline import StudyPlanExtractionPipeline

            return StudyPlanExtractionPipeline(
                result_dir,
                workers=request.workers,
                reader_backend=request.reader_backend,
                resume=request.resume,
            ).run()
        if operation == "extract_semantics":
            from .adapter.study_plans.semantics import enrich_existing_dataset

            return enrich_existing_dataset(result_dir)
        if operation == "compact_study_plans":
            from .adapter.study_plans.compact import compact_existing_dataset

            return compact_existing_dataset(result_dir)
        raise ValueError(f"Unsupported BMSTU operation: {operation}")


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
