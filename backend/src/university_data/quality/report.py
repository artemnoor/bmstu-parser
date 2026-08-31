from __future__ import annotations

from typing import Any


def build_quality_report(
    university_id: str,
    capabilities: dict[str, bool],
    records: dict[str, list[dict[str, Any]]],
    *,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    errors = list(errors or [])
    unsupported = [name for name, supported in capabilities.items() if not supported]
    statuses = {
        name: "published" if supported else "not_supported"
        for name, supported in capabilities.items()
    }
    counts = {name: len(items) for name, items in records.items()}
    return {
        "schema_version": "1.0",
        "university_id": university_id,
        "capabilities": capabilities,
        "capability_status": statuses,
        "counts": counts,
        "unsupported": unsupported,
        "errors": errors,
        "verification": {"passed": not errors},
    }
