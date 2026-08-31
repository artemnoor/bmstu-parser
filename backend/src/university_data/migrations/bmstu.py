from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from bmstu_parser.ingestion.mirror_api import DetailFetch
from bmstu_parser.outputs.writers import write_dataset
from bmstu_parser.quality.checks import validate_dataset
from bmstu_parser.transform.normalize import Normalizer
from bmstu_parser.transform.ontology import OntologyBuilder

from ..core.source_models import SourceProgram
from ..domain.ids import global_stable_id
from ..domain.provenance import FieldMeta, SourceProvenance
from ..normalization import CanonicalNormalizer
from ..ontology import build_ontology
from ..quality import build_quality_report
from ..storage import UniversityStorage


class BmstuRawReplayProvider:
    """Replay a previously captured raw snapshot without network access."""

    def __init__(self, source_dir: Path) -> None:
        self.source_dir = source_dir

    def fetch(self) -> tuple[list[dict[str, Any]], dict[str, Any], list[DetailFetch]]:
        payload = json.loads(
            (self.source_dir / "raw/majors_list.json").read_text(encoding="utf-8")
        )
        summaries = payload.get("data", []) if isinstance(payload, dict) else []
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        details: list[DetailFetch] = []
        for path in sorted((self.source_dir / "raw/details").glob("*.json")):
            item = json.loads(path.read_text(encoding="utf-8"))
            details.append(
                DetailFetch(
                    item.get("summary", {}),
                    item.get("detail"),
                    item.get("error"),
                    item.get("fetched_at_utc", ""),
                )
            )
        return (
            [item for item in summaries if isinstance(item, dict)],
            dict(meta),
            details,
        )


def _collect_ids(value: Any, result: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "id" and isinstance(item, str) and item.startswith("bmstu:"):
                result.add(item)
            _collect_ids(item, result)
    elif isinstance(value, list):
        for item in value:
            _collect_ids(item, result)


def _global_aliases(majors: list[Any]) -> list[dict[str, str]]:
    aliases: dict[str, str] = {}

    def collect(value: Any, entity_type: str) -> None:
        if isinstance(value, dict):
            identifier = value.get("id")
            if isinstance(identifier, str) and identifier.startswith("bmstu:"):
                aliases.setdefault(
                    identifier, global_stable_id("bmstu", entity_type, identifier)
                )
            for key, child in value.items():
                child_type = {
                    "faculties": "faculty",
                    "departments": "department",
                    "educational_programs": "program",
                    "entrance_requirements": "admission_requirement",
                    "tuition": "tuition_option",
                    "places": "admission_place",
                    "historical_passing_scores": "historical_passing_score",
                    "practice_partners": "practice_partner",
                }.get(key, entity_type)
                collect(child, child_type)
        elif isinstance(value, list):
            for child in value:
                collect(child, entity_type)

    for major in majors:
        aliases[major.id] = global_stable_id(
            "bmstu", "study_direction", major.slug or major.code or major.name
        )
        for department in major.departments:
            aliases[department.id] = global_stable_id(
                "bmstu",
                "department",
                department.slug or department.code or department.name,
            )
            for program in department.educational_programs:
                aliases[program.id] = global_stable_id(
                    "bmstu", "program", program.code or program.name or program.id
                )
                for requirement in major.entrance_requirements:
                    if requirement.id.startswith("bmstu:"):
                        aliases[requirement.id] = global_stable_id(
                            "bmstu", "admission_requirement", requirement.id
                        )
                for tuition in major.tuition:
                    if tuition.id.startswith("bmstu:"):
                        aliases[tuition.id] = global_stable_id(
                            "bmstu", "tuition_option", tuition.id
                        )
        collect(asdict(major), "study_direction")
    return [
        {
            "legacy_id": legacy,
            "canonical_id": canonical,
            "entity_type": canonical.split(":")[2],
        }
        for legacy, canonical in sorted(aliases.items())
        if legacy != canonical
    ]


def _write_platform_projection(
    output_dir: Path, majors: list[Any]
) -> dict[str, list[dict[str, Any]]]:
    normalizer = CanonicalNormalizer()
    faculties: list[dict[str, Any]] = []
    faculty_ids: dict[str, str] = {}
    directions: list[dict[str, Any]] = []
    departments: list[dict[str, Any]] = []
    department_ids: dict[str, str] = {}
    programs: list[dict[str, Any]] = []
    admission: list[dict[str, Any]] = []
    tuition: list[dict[str, Any]] = []
    for major in majors:
        direction_key = major.slug or major.code or major.name
        direction_id = global_stable_id("bmstu", "study_direction", direction_key)
        for faculty in major.faculties:
            faculty_key = faculty.slug or faculty.code or faculty.name
            faculty_id = global_stable_id("bmstu", "faculty", faculty_key)
            faculty_ids[faculty.id] = faculty_id
            if not any(item["id"] == faculty_id for item in faculties):
                faculties.append(
                    {
                        "id": faculty_id,
                        "university_id": "bmstu",
                        "name": faculty.name,
                        "code": faculty.code,
                        "field_meta": {
                            "name": FieldMeta("published", "source", 1.0).to_dict()
                        },
                        "extensions": {},
                        "provenance": faculty.provenance.to_dict(),
                    }
                )
        directions.append(
            {
                "id": direction_id,
                "university_id": "bmstu",
                "name": major.name,
                "code": major.code,
                "status": major.status,
                "field_meta": {"name": FieldMeta("published", "source", 1.0).to_dict()},
                "extensions": {},
                "provenance": major.provenance.to_dict(),
            }
        )
        for department in major.departments:
            department_id = global_stable_id(
                "bmstu",
                "department",
                department.slug or department.code or department.name,
            )
            department_ids[department.id] = department_id
            departments.append(
                {
                    "id": department_id,
                    "university_id": "bmstu",
                    "name": department.name,
                    "faculty_id": faculty_ids.get(
                        department.faculty_id,
                        global_stable_id("bmstu", "faculty", department.faculty_id),
                    ),
                    "code": department.code,
                    "field_meta": {
                        "name": FieldMeta("published", "source", 1.0).to_dict()
                    },
                    "extensions": {},
                    "provenance": department.provenance.to_dict(),
                }
            )
        for program in major.educational_programs:
            source = SourceProgram(
                source_key=program.code or program.name or program.id,
                name=program.name,
                code=program.code,
                study_direction_key=major.slug or major.code,
                department_key=program.department_id,
                description=program.description,
                study_plan_url=program.study_plan_url,
                raw=asdict(program),
                provenance=SourceProvenance(
                    source_page=major.provenance.source_page,
                    list_api=major.provenance.list_api,
                    detail_api=major.provenance.detail_api,
                    detail_page=major.provenance.detail_page,
                    fetched_at_utc=major.provenance.fetched_at_utc,
                    raw_snapshot_path=major.provenance.raw_snapshot_path,
                    source_key=program.id,
                ),
            )
            program_row = normalizer.program("bmstu", source)
            if program.department_id:
                program_row["department_id"] = department_ids.get(
                    program.department_id, ""
                )
            programs.append(program_row)
        for requirement in major.entrance_requirements:
            admission.append(
                {
                    "id": global_stable_id(
                        "bmstu",
                        "admission_requirement",
                        requirement.subject,
                        direction_key,
                    ),
                    "university_id": "bmstu",
                    "study_direction_id": direction_id,
                    "subject": requirement.subject,
                    "minimum_score": requirement.minimum_score,
                    "is_choice": requirement.is_choice,
                    "field_meta": {
                        "minimum_score": FieldMeta(
                            "published"
                            if requirement.minimum_score is not None
                            else "not_published",
                            "source",
                            1.0 if requirement.minimum_score is not None else 0.0,
                        ).to_dict()
                    },
                    "extensions": {},
                    "provenance": requirement.provenance.to_dict(),
                }
            )
        for option in major.tuition:
            tuition.append(
                {
                    "id": global_stable_id(
                        "bmstu",
                        "tuition_option",
                        option.study_form,
                        option.term,
                        direction_key,
                    ),
                    "university_id": "bmstu",
                    "study_direction_id": direction_id,
                    "study_form": option.study_form,
                    "value": option.value,
                    "currency": option.currency,
                    "term": option.term,
                    "field_meta": {
                        "value": FieldMeta(
                            "published"
                            if option.value is not None
                            else "not_published",
                            "source",
                            1.0 if option.value is not None else 0.0,
                        ).to_dict()
                    },
                    "extensions": {},
                    "provenance": option.provenance.to_dict(),
                }
            )
    storage = UniversityStorage(output_dir.parent, "bmstu")
    storage.path = output_dir
    records = {
        "faculties": faculties,
        "study_directions": directions,
        "departments": departments,
        "programs": programs,
        "admission_requirements": admission,
        "tuition_options": tuition,
    }
    storage.write_json(
        "canonical/catalog.json",
        {
            "university_id": "bmstu",
            "records": records,
            "quality": {
                "counts": {name: len(items) for name, items in records.items()}
            },
        },
    )
    storage.write_json("ontology.json", build_ontology("bmstu", records))
    storage.write_json(
        "quality/report.json",
        build_quality_report(
            "bmstu",
            {
                "programs": True,
                "curricula": True,
                "faculties": True,
                "departments": True,
                "admission": True,
                "tuition": True,
                "teachers": False,
            },
            records,
        ),
    )
    for name, items in records.items():
        storage.write_jsonl(f"canonical/{name}.jsonl", items)
        storage.write_csv(f"canonical/{name}.csv", items)
    return records


def migrate_bmstu(
    from_dir: Path,
    to_dir: Path,
    *,
    rebuild_derived: bool = True,
    write_aliases: bool = True,
) -> dict[str, Any]:
    source_dir = from_dir.resolve()
    target_dir = to_dir.resolve()
    if target_dir == source_dir or target_dir in source_dir.parents:
        raise ValueError(
            "Migration target must be a new child or sibling result directory"
        )
    replay = BmstuRawReplayProvider(source_dir)
    summaries, list_meta, details = replay.fetch()
    majors = [Normalizer().normalize(item) for item in details]
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target_dir.name}.migration-", dir=target_dir.parent)
    )
    try:
        if (source_dir / "raw").is_dir():
            shutil.copytree(source_dir / "raw", staging / "raw", dirs_exist_ok=True)
        if (source_dir / "study_plans").is_dir():
            shutil.copytree(
                source_dir / "study_plans", staging / "study_plans", dirs_exist_ok=True
            )
        if (source_dir / "study_plan_data").is_dir():
            shutil.copytree(
                source_dir / "study_plan_data",
                staging / "study_plan_data",
                dirs_exist_ok=True,
            )
        legacy_quality = validate_dataset(
            summaries, list_meta, details, majors, OntologyBuilder().build(majors)
        )
        platform_records: dict[str, list[dict[str, Any]]] = {}
        if rebuild_derived:
            write_dataset(
                staging,
                majors,
                OntologyBuilder().build(majors),
                legacy_quality,
                summaries,
                list_meta,
                details,
                "replayed",
            )
            platform_records = _write_platform_projection(staging, majors)
            # ``write_dataset`` intentionally creates normalized raw files for
            # a live run.  A replay must preserve the captured bytes exactly,
            # so restore the source snapshots after materialization.
            shutil.copytree(source_dir / "raw", staging / "raw", dirs_exist_ok=True)
        if write_aliases:
            (staging / "id_aliases.json").write_text(
                json.dumps(
                    {"schema_version": "2.0", "aliases": _global_aliases(majors)},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        quality = (
            build_quality_report(
                "bmstu",
                {
                    "programs": True,
                    "curricula": True,
                    "faculties": True,
                    "departments": True,
                    "admission": True,
                    "tuition": True,
                    "teachers": False,
                },
                platform_records
                or {"study_directions": [asdict(major) for major in majors]},
                errors=(
                    []
                    if legacy_quality.get("verification", {}).get("passed", False)
                    else ["Legacy BMSTU quality gate failed"]
                ),
            )
            if rebuild_derived
            else dict(legacy_quality)
        )
        quality["legacy_quality"] = legacy_quality
        quality["migration"] = {
            "source": str(source_dir),
            "target": str(target_dir),
            "replayed": True,
            "raw_preserved": (staging / "raw").is_dir(),
        }
        (staging / "quality").mkdir(exist_ok=True)
        (staging / "quality/report.json").write_text(
            json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if not quality.get("verification", {}).get("passed", False):
            raise RuntimeError("BMSTU migration quality gate failed")
        if target_dir.exists():
            raise FileExistsError(f"Migration target already exists: {target_dir}")
        staging.replace(target_dir)
        return quality
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
