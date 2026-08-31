from __future__ import annotations

from typing import Any


def build_quality_report(
    university_id: str,
    capabilities: dict[str, bool],
    records: dict[str, list[dict[str, Any]]],
    *,
    errors: list[str] | None = None,
    ontology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors = list(errors or [])
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
    if ontology is not None:
        object_ids = {
            item.get("id")
            for item in ontology.get("objects", [])
            if isinstance(item, dict)
        }
        orphan_links = [
            link
            for link in ontology.get("links", [])
            if isinstance(link, dict)
            and link.get("to") not in object_ids
            and link.get("target_type") != "university"
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
            "orphan_links": len(orphan_links),
        },
        "verification": {"passed": not errors},
    }
