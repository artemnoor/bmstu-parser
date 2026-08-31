from __future__ import annotations

from collections import Counter
from typing import Any

from ..domain.models import Major
from ..ingestion.mirror_api import DetailFetch


def _meta_count(meta: dict[str, Any]) -> int | None:
    value = meta.get("count")
    return value if isinstance(value, int) else None


def validate_dataset(
    summaries: list[dict[str, Any]],
    list_meta: dict[str, Any],
    details: list[DetailFetch],
    majors: list[Major],
    ontology: dict[str, Any],
) -> dict[str, Any]:
    slugs = [str(item.get("slug", "")) for item in summaries]
    duplicates = sorted({slug for slug in slugs if slug and slugs.count(slug) > 1})
    summary_slugs = Counter(slugs)
    detail_slugs = Counter(str(item.summary.get("slug", "")) for item in details)
    missing_detail_items = sorted(
        slug for slug, count in summary_slugs.items() if slug and detail_slugs[slug] != count
    )
    unexpected_detail_items = sorted(
        slug for slug, count in detail_slugs.items() if slug and summary_slugs[slug] != count
    )
    duplicate_detail_items = sorted(slug for slug, count in detail_slugs.items() if slug and count > 1)
    detail_errors = [
        {"slug": item.summary.get("slug", ""), "error": item.error}
        for item in details
        if item.error
    ]
    missing_major_fields = [
        {"slug": major.slug, "missing": [field for field, value in (("name", major.name), ("code", major.code)) if not value]}
        for major in majors
        if not major.name or not major.code
    ]
    missing_program_fields: list[dict[str, Any]] = []
    orphan_programs: list[dict[str, Any]] = []
    plan_errors: list[dict[str, Any]] = []
    plan_statuses: Counter[str] = Counter()
    program_count = 0
    department_count = 0
    for major in majors:
        department_count += len(major.departments)
        for program in major.educational_programs:
            program_count += 1
            missing = [
                field
                for field, value in (("name", program.name), ("code", program.code), ("department_id", program.department_id))
                if not value
            ]
            if missing:
                missing_program_fields.append({"major_slug": major.slug, "program_id": program.id, "missing": missing})
            if program.department_id not in {department.id for department in major.departments}:
                orphan_programs.append({"major_slug": major.slug, "program_id": program.id})
            plan_statuses[program.study_plan.status] += 1
            if program.study_plan.status == "error" or any(file_info.download_error for file_info in program.study_plan.files):
                plan_errors.append(
                    {
                        "major_slug": major.slug,
                        "program_id": program.id,
                        "status": program.study_plan.status,
                        "error": program.study_plan.error,
                        "files": [
                            {"name": file_info.name, "error": file_info.download_error}
                            for file_info in program.study_plan.files
                            if file_info.download_error
                        ],
                    }
                )

    object_ids = {
        object_item["id"]
        for bucket in ontology.get("objects", {}).values()
        for object_item in bucket
        if isinstance(object_item, dict) and object_item.get("id")
    }
    orphan_links = [
        link
        for link in ontology.get("links", [])
        if link.get("from_id") not in object_ids or link.get("to_id") not in object_ids
    ]

    expected_count = _meta_count(list_meta)
    checks = {
        "list_count_matches_api_meta": expected_count is None or expected_count == len(summaries),
        "no_duplicate_slugs": not duplicates,
        "detail_for_every_list_item": (
            len(details) == len(summaries)
            and not missing_detail_items
            and not unexpected_detail_items
            and not duplicate_detail_items
        ),
        "all_detail_requests_succeeded": not detail_errors,
        "all_details_have_name_and_code": not missing_major_fields,
        "all_programs_have_department_context": not missing_program_fields and not orphan_programs,
        "ontology_has_no_orphan_links": not orphan_links,
        "no_plan_errors": not plan_errors,
    }
    checks["passed"] = all(checks.values())

    return {
        "verification": checks,
        "counts": {
            "list_items": len(summaries),
            "api_meta_count": expected_count,
            "detail_items": len(details),
            "majors": len(majors),
            "departments": department_count,
            "educational_programs": program_count,
            "ontology_objects": sum(len(bucket) for bucket in ontology.get("objects", {}).values()),
            "ontology_links": len(ontology.get("links", [])),
        },
        "plan_statuses": dict(sorted(plan_statuses.items())),
        "detail_errors": detail_errors,
        "missing_detail_items": missing_detail_items,
        "unexpected_detail_items": unexpected_detail_items,
        "duplicate_detail_items": duplicate_detail_items,
        "missing_major_fields": missing_major_fields,
        "missing_program_fields": missing_program_fields,
        "orphan_programs": orphan_programs,
        "orphan_links": orphan_links,
        "plan_errors": plan_errors,
    }
