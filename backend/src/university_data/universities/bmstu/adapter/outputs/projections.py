from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from ..domain.models import Major
from ..transform.text import json_cell


def _records(majors: Iterable[Major]) -> list[dict[str, Any]]:
    return [major.to_dict() for major in majors]


def major_rows(majors: Iterable[Major]) -> list[dict[str, Any]]:
    rows = []
    for major in majors:
        rows.append(
            {
                "id": major.id,
                "status": major.status,
                "detail_error": major.detail_error or "",
                "slug": major.slug,
                "code": major.code,
                "name": major.name,
                "qualification": major.qualification,
                "science_degree": major.science_degree,
                "study_period": major.study_period,
                "military": major.military,
                "description": major.description,
                "faculty_id": major.faculty_id,
                "faculty_name": major.faculty_name,
                "faculties": json_cell([asdict(item) for item in major.faculties]),
                "tuition": json_cell([asdict(item) for item in major.tuition]),
                "entrance_requirements": json_cell(
                    [asdict(item) for item in major.entrance_requirements]
                ),
                "places": json_cell([asdict(item) for item in major.places]),
                "department_count": len(major.departments),
                "program_count": len(major.educational_programs),
                "source_page": major.provenance.source_page,
                "detail_api": major.provenance.detail_api,
                "raw_snapshot_path": major.provenance.raw_snapshot_path,
            }
        )
    return rows


def department_rows(majors: Iterable[Major]) -> list[dict[str, Any]]:
    rows = []
    for major in majors:
        for department in major.departments:
            rows.append(
                {
                    "id": department.id,
                    "major_id": major.id,
                    "major_slug": major.slug,
                    "major_code": major.code,
                    "major_name": major.name,
                    "slug": department.slug,
                    "code": department.code,
                    "name": department.name,
                    "faculty_id": department.faculty_id,
                    "faculty_name": department.faculty_name,
                    "realized_programs": json_cell(department.realized_programs),
                    "short_description": department.short_description,
                    "description": department.description,
                    "practice_description": department.practice_description,
                    "key_disciplines": json_cell(department.key_disciplines),
                    "historical_passing_scores": json_cell(
                        [asdict(item) for item in department.historical_passing_scores]
                    ),
                    "program_count": len(department.educational_programs),
                    "phone": department.phone,
                    "address": department.address,
                    "site": department.site,
                }
            )
    return rows


def educational_program_rows(majors: Iterable[Major]) -> list[dict[str, Any]]:
    rows = []
    for major in majors:
        for program in major.educational_programs:
            rows.append(
                {
                    "id": program.id,
                    "legacy_id": program.legacy_id,
                    "major_id": major.id,
                    "major_slug": major.slug,
                    "major_code": major.code,
                    "major_name": major.name,
                    "department_id": program.department_id,
                    "department_name": program.department_name,
                    "name": program.name,
                    "code": program.code,
                    "enrollment_available": program.enrollment_available,
                    "location": program.location,
                    "description": program.description,
                    "disciplines": json_cell(program.disciplines),
                    "study_plan_url": program.study_plan_url,
                    "study_plan_status": program.study_plan.status,
                    "study_plan_files": len(program.study_plan.files),
                    "practice_partners": json_cell(
                        [asdict(item) for item in program.practice_partners]
                    ),
                    "source_page": program.provenance.detail_page,
                }
            )
    return rows


def entrance_subject_rows(majors: Iterable[Major]) -> list[dict[str, Any]]:
    rows = []
    for major in majors:
        for requirement in major.entrance_requirements:
            rows.append(
                {
                    "id": requirement.id,
                    "legacy_id": requirement.legacy_id,
                    "major_id": major.id,
                    "major_slug": major.slug,
                    "major_code": major.code,
                    "major_name": major.name,
                    "subject": requirement.subject,
                    "minimum_score": requirement.minimum_score,
                    "is_choice": requirement.is_choice,
                    "requirement_type": requirement.requirement_type,
                    "minimum_score_raw": requirement.minimum_score_raw,
                    "normalization_warnings": json_cell(
                        requirement.normalization_warnings
                    ),
                }
            )
    return rows


def tuition_rows(majors: Iterable[Major]) -> list[dict[str, Any]]:
    rows = []
    for major in majors:
        for tuition in major.tuition:
            rows.append(
                {
                    "id": tuition.id,
                    "legacy_id": tuition.legacy_id,
                    "major_id": major.id,
                    "major_slug": major.slug,
                    "major_code": major.code,
                    "major_name": major.name,
                    "study_form": tuition.study_form,
                    "value": tuition.value,
                    "discount_value": tuition.discount_value,
                    "currency": tuition.currency,
                    "term": tuition.term,
                    "discount_url": tuition.discount_url,
                    "subtitle": tuition.subtitle,
                    "value_raw": tuition.value_raw,
                    "discount_value_raw": tuition.discount_value_raw,
                    "normalization_warnings": json_cell(tuition.normalization_warnings),
                }
            )
    return rows


def discipline_rows(majors: Iterable[Major]) -> list[dict[str, Any]]:
    rows = []
    for major in majors:
        for discipline in major.key_disciplines:
            rows.append(
                {
                    "major_id": major.id,
                    "major_slug": major.slug,
                    "scope": "major",
                    "owner_id": major.id,
                    "owner_name": major.name,
                    "discipline": discipline,
                }
            )
        for department in major.departments:
            for discipline in department.key_disciplines:
                rows.append(
                    {
                        "major_id": major.id,
                        "major_slug": major.slug,
                        "scope": "department",
                        "owner_id": department.id,
                        "owner_name": department.name,
                        "discipline": discipline,
                    }
                )
            for program in department.educational_programs:
                for discipline in program.disciplines:
                    rows.append(
                        {
                            "major_id": major.id,
                            "major_slug": major.slug,
                            "scope": "program",
                            "owner_id": program.id,
                            "owner_name": program.name,
                            "discipline": discipline,
                        }
                    )
    return rows


def historical_score_rows(majors: Iterable[Major]) -> list[dict[str, Any]]:
    rows = []
    for major in majors:
        for score in major.historical_passing_scores:
            rows.append(
                {
                    "id": score.id,
                    "legacy_id": score.legacy_id,
                    "major_id": major.id,
                    "major_slug": major.slug,
                    "major_code": major.code,
                    "major_name": major.name,
                    "department_id": score.department_id,
                    "department_name": score.department_name,
                    "year": score.year,
                    "score": score.score,
                    "year_raw": score.year_raw,
                    "score_raw": score.score_raw,
                    "normalization_warnings": json_cell(score.normalization_warnings),
                }
            )
    return rows


def study_plan_file_rows(majors: Iterable[Major]) -> list[dict[str, Any]]:
    rows = []
    for major in majors:
        for program in major.educational_programs:
            for file_info in program.study_plan.files:
                rows.append(
                    {
                        "id": file_info.id,
                        "major_id": major.id,
                        "major_slug": major.slug,
                        "major_code": major.code,
                        "major_name": major.name,
                        "program_id": program.id,
                        "program_code": program.code,
                        "program_name": program.name,
                        "plan_url": program.study_plan.url,
                        "plan_status": program.study_plan.status,
                        "name": file_info.name,
                        "path": file_info.path,
                        "size": file_info.size,
                        "mime_type": file_info.mime_type,
                        "md5": file_info.md5,
                        "sha256": file_info.sha256,
                        "source_url": file_info.source_url,
                        "resolved_url": file_info.resolved_url,
                        "download_url": file_info.download_url,
                        "local_path": file_info.local_path,
                        "downloaded": file_info.downloaded,
                        "downloaded_size": file_info.downloaded_size,
                        "download_error": file_info.download_error or "",
                        "size_raw": file_info.size_raw,
                        "normalization_warnings": json_cell(
                            file_info.normalization_warnings
                        ),
                    }
                )
    return rows


def canonical_records(majors: Iterable[Major]) -> list[dict[str, Any]]:
    return _records(majors)


def id_aliases(majors: Iterable[Major]) -> list[dict[str, str]]:
    """Expose migrations from index-based IDs to business-key IDs."""

    aliases: list[dict[str, str]] = []

    def add(entity_type: str, identifier: str, legacy_id: str) -> None:
        if legacy_id and legacy_id != identifier:
            aliases.append(
                {
                    "legacy_id": legacy_id,
                    "canonical_id": identifier,
                    "entity_type": entity_type,
                }
            )

    for major in majors:
        for requirement in major.entrance_requirements:
            add("entrance_requirement", requirement.id, requirement.legacy_id)
        for tuition in major.tuition:
            add("tuition_option", tuition.id, tuition.legacy_id)
        for place in major.places:
            add("admission_place", place.id, place.legacy_id)
        for score in major.historical_passing_scores:
            add("historical_passing_score", score.id, score.legacy_id)
        for department in major.departments:
            for program in department.educational_programs:
                add("educational_program", program.id, program.legacy_id)
    return sorted(
        aliases,
        key=lambda item: (item["entity_type"], item["legacy_id"], item["canonical_id"]),
    )
