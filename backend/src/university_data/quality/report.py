from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..core.capabilities import CapabilitySpec
from ..core.capability_registry import CORE_CAPABILITY_DEFINITIONS
from ..domain.provenance import (
    provenance_has_source_locator,
    provenance_source_key,
)


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


def _unresolved_reference_gaps(
    university_id: str,
    records: dict[str, list[dict[str, Any]]],
) -> list[tuple[str, str, str, str]]:
    dataset_capabilities = {
        dataset: definition.name
        for definition in CORE_CAPABILITY_DEFINITIONS.values()
        for dataset in definition.datasets
    }
    result: list[tuple[str, str, str, str]] = []
    for dataset, items in records.items():
        capability = dataset_capabilities.get(dataset)
        if capability is None:
            continue
        for item in items:
            extensions = item.get("extensions")
            namespace = (
                extensions.get(university_id) if isinstance(extensions, dict) else None
            )
            references = (
                namespace.get("unresolved_references")
                if isinstance(namespace, dict)
                else None
            )
            if not isinstance(references, dict):
                continue
            for field_name, source_key in references.items():
                if isinstance(source_key, str) and source_key.strip():
                    result.append(
                        (
                            capability,
                            str(item.get("id", "")),
                            str(field_name),
                            source_key,
                        )
                    )
    return result


def build_quality_report(
    university_id: str,
    capabilities: dict[str, bool] | Iterable[CapabilitySpec],
    records: dict[str, list[dict[str, Any]]],
    *,
    errors: list[str] | None = None,
    ontology: dict[str, Any] | None = None,
    capability_states: dict[str, str] | None = None,
    capability_warnings: dict[str, list[str]] | None = None,
    capability_gaps: dict[str, list[dict[str, str]]] | None = None,
    capability_metrics: dict[str, dict[str, Any]] | None = None,
    module_version: str | None = None,
    module_config_hash: str | None = None,
    active_snapshot: str | None = None,
) -> dict[str, Any]:
    errors = list(errors or [])
    if isinstance(capabilities, dict):
        capability_map = dict(capabilities)
        allow_partial: set[str] = set()
    else:
        specs = tuple(capabilities)
        capability_map = {item.name: item.enabled for item in specs}
        allow_partial = {item.name for item in specs if item.allow_partial}
    capability_states = dict(capability_states or {})
    capability_warnings = {
        key: list(value) for key, value in (capability_warnings or {}).items()
    }
    capability_gaps = {
        key: list(value) for key, value in (capability_gaps or {}).items()
    }
    capability_metrics = {
        key: dict(value) for key, value in (capability_metrics or {}).items()
    }
    enabled_quality_checks = {
        check
        for name, supported in capability_map.items()
        if supported
        for check in CORE_CAPABILITY_DEFINITIONS[name].quality_checks
    }
    for capability, record_id, field_name, source_key in _unresolved_reference_gaps(
        university_id, records
    ):
        capability_warnings.setdefault(capability, []).append(
            f"unresolved optional reference {field_name!r} on {record_id or 'record'}"
        )
        capability_gaps.setdefault(capability, []).append(
            {
                "code": "optional_relation_unresolved",
                "message": f"{field_name} points to an unavailable capability",
                "source_key": source_key,
            }
        )
    duplicate_ids = _duplicate_ids(records)
    missing_ids = {
        dataset: sum(1 for item in items if not item.get("id"))
        for dataset, items in records.items()
        if any(not item.get("id") for item in items)
    }
    unsupported = [name for name, supported in capability_map.items() if not supported]
    statuses = {}
    for name, supported in capability_map.items():
        if not supported:
            statuses[name] = "not_supported"
        elif capability_states.get(name) in {"failed", "not_published"}:
            statuses[name] = capability_states[name]
        elif not records.get(CORE_CAPABILITY_DEFINITIONS[name].primary_dataset):
            if capability_states.get(name) == "degraded" and name in allow_partial:
                statuses[name] = "degraded"
                continue
            statuses[name] = "not_published"
            errors.append(
                f"supported capability {name!r} produced no canonical records"
            )
        else:
            statuses[name] = capability_states.get(name, "published")
    counts = {name: len(items) for name, items in records.items()}
    record_scope_ok = all(
        item.get("university_id") == university_id
        for items in records.values()
        for item in items
    )
    provenance_ok = all(
        isinstance(item.get("provenance"), dict)
        and bool(provenance_source_key(item["provenance"]))
        and provenance_has_source_locator(item["provenance"])
        for dataset, items in records.items()
        if dataset != "universities"
        for item in items
    )
    if "records_university_scoped" in enabled_quality_checks and not record_scope_ok:
        errors.append("record has a university_id outside the current scope")
    if "provenance_present" in enabled_quality_checks and not provenance_ok:
        errors.append("record is missing provenance")
    if "record_ids_unique" in enabled_quality_checks and duplicate_ids:
        errors.append(f"duplicate canonical IDs: {duplicate_ids}")
    if "record_ids_present" in enabled_quality_checks and missing_ids:
        errors.append(f"records are missing IDs: {missing_ids}")
    semantic_failures = _semantic_failures(records)
    if "semantic_study_plans" in enabled_quality_checks and semantic_failures:
        errors.append(
            f"semantic study-plan quality failed for {len(semantic_failures)} curricula"
        )
    if ontology is not None:
        orphan_links = [
            link for link in ontology.get("broken_links", []) if isinstance(link, dict)
        ]
    else:
        orphan_links = []
    if "orphan_links" in enabled_quality_checks and orphan_links:
        errors.append(f"ontology contains {len(orphan_links)} orphan links")
    configured_quality_checks = {
        name: list(CORE_CAPABILITY_DEFINITIONS[name].quality_checks)
        for name in capability_map
    }
    metrics = {
        "records": sum(
            int(item.get("records", 0)) for item in capability_metrics.values()
        ),
        "warnings": sum(len(items) for items in capability_warnings.values()),
        "gaps": sum(len(items) for items in capability_gaps.values()),
        "failures": sum(
            int(item.get("failures", 0)) for item in capability_metrics.values()
        ),
        "duration_ms": round(
            sum(
                float(item.get("duration_ms", 0.0))
                for item in capability_metrics.values()
            ),
            3,
        ),
        "active_snapshot": active_snapshot or "",
        "adapter_version": module_version or "",
        "config_hash": module_config_hash or "",
    }
    return {
        "schema_version": "1.0",
        "university_id": university_id,
        "capabilities": capability_map,
        "capability_status": statuses,
        "capability_warnings": capability_warnings,
        "capability_gaps": capability_gaps,
        "capability_metrics": capability_metrics,
        "capability_quality_checks": configured_quality_checks,
        "metrics": metrics,
        "module_version": module_version or "",
        "module_config_hash": module_config_hash or "",
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
