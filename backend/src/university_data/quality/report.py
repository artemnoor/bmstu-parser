from __future__ import annotations

from typing import Any


def _duplicate_ids(records: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for dataset, items in records.items():
        seen: set[str] = set()
        duplicates: set[str] = set()
        for item in items:
            identifier = str(item.get("id", ""))
            if identifier and identifier in seen:
                duplicates.add(identifier)
            if identifier:
                seen.add(identifier)
        if duplicates:
            result[dataset] = sorted(duplicates)
    return result


def _semantic_failures(
    records: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for curriculum in records.get("curricula", []):
        extensions = curriculum.get("extensions", {})
        if not isinstance(extensions, dict):
            continue
        for namespace, values in extensions.items():
            if not isinstance(values, dict):
                continue
            reports = values.get("semantic_reports")
            if not isinstance(reports, list):
                report = values.get("semantic_report")
                reports = [report] if isinstance(report, dict) else []
            for report in reports:
                if not isinstance(report, dict):
                    continue
                verification = report.get("verification", {})
                if verification.get("passed") is False:
                    failures.append(
                        {
                            "curriculum_id": curriculum.get("id", ""),
                            "namespace": namespace,
                            "report": report,
                        }
                    )
            warnings = values.get("semantic_warnings")
            if isinstance(warnings, list) and warnings:
                failures.append(
                    {
                        "curriculum_id": curriculum.get("id", ""),
                        "namespace": namespace,
                        "warnings": warnings,
                    }
                )
    return failures


def build_quality_report(
    university_id: str,
    capabilities: dict[str, bool],
    records: dict[str, list[dict[str, Any]]],
    *,
    errors: list[str] | None = None,
    ontology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors = list(errors or [])
    duplicate_ids = _duplicate_ids(records)
    missing_ids = {
        dataset: sum(1 for item in items if not item.get("id"))
        for dataset, items in records.items()
        if any(not item.get("id") for item in items)
    }
    unsupported = [name for name, supported in capabilities.items() if not supported]
    dataset_for_capability = {
        "programs": "programs",
        "curricula": "curricula",
        "faculties": "faculties",
        "departments": "departments",
        "admission": "admission_requirements",
        "tuition": "tuition_options",
        "teachers": "teachers",
    }
    statuses = {}
    for name, supported in capabilities.items():
        if not supported:
            statuses[name] = "not_supported"
        elif not records.get(dataset_for_capability.get(name, name)):
            statuses[name] = "not_published"
        else:
            statuses[name] = "published"
    counts = {name: len(items) for name, items in records.items()}
    record_scope_ok = all(
        item.get("university_id") == university_id
        for items in records.values()
        for item in items
    )
    provenance_ok = all(
        isinstance(item.get("provenance"), dict)
        for items in records.values()
        for item in items
    )
    if not record_scope_ok:
        errors.append("record has a university_id outside the current scope")
    if not provenance_ok:
        errors.append("record is missing provenance")
    if duplicate_ids:
        errors.append(f"duplicate canonical IDs: {duplicate_ids}")
    if missing_ids:
        errors.append(f"records are missing IDs: {missing_ids}")
    semantic_failures = _semantic_failures(records)
    if semantic_failures:
        errors.append(
            f"semantic study-plan quality failed for {len(semantic_failures)} curricula"
        )
    if ontology is not None:
        orphan_links = [
            link for link in ontology.get("broken_links", []) if isinstance(link, dict)
        ]
    else:
        orphan_links = []
    if orphan_links:
        errors.append(f"ontology contains {len(orphan_links)} orphan links")
    return {
        "schema_version": "1.0",
        "university_id": university_id,
        "capabilities": capabilities,
        "capability_status": statuses,
        "counts": counts,
        "unsupported": unsupported,
        "errors": errors,
        "checks": {
            "records_university_scoped": record_scope_ok,
            "provenance_present": provenance_ok,
            "record_ids_unique": not duplicate_ids,
            "record_ids_present": not missing_ids,
            "orphan_links": len(orphan_links),
            "semantic_study_plans": not semantic_failures,
        },
        "duplicates": duplicate_ids,
        "missing_ids": missing_ids,
        "semantic_failures": semantic_failures,
        "broken_links": orphan_links,
        "verification": {"passed": not errors},
    }
