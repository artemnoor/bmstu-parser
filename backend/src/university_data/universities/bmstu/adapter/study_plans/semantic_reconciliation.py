from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def reconcile_totals(
    disciplines: list[dict[str, Any]], loads: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compare declared curriculum totals with allocated semester rows.

    The balancing policy is intentionally diagnostic: an ambiguous PDF value
    is never silently redistributed. This preserves the parser's existing
    behavior and makes a mismatch an explicit quality-gate signal.
    """

    sums: defaultdict[str, defaultdict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    active: Counter[str] = Counter()
    for load in loads:
        identifier = load["discipline_id"]
        if load.get("has_numeric_load"):
            active[identifier] += 1
        for field in (
            "credits",
            "hours",
            "audited_hours",
            "independent_or_other_hours",
        ):
            value = load.get(field)
            if value is not None:
                sums[identifier][field] += float(value)
    exact = 0
    unallocated: list[dict[str, Any]] = []
    active_mismatches: list[dict[str, Any]] = []
    for discipline in disciplines:
        identifier = discipline["id"]
        expected = {
            "credits": discipline["workload"].get("credits"),
            "hours": discipline["workload"].get("hours"),
            "audited_hours": discipline["workload"].get("audited_hours"),
            "independent_or_other_hours": discipline["class_hours"].get(
                "independent_or_other"
            ),
        }
        differences = {
            field: sums[identifier][field] - float(value)
            for field, value in expected.items()
            if value is not None and abs(sums[identifier][field] - float(value)) > 0.01
        }
        if not differences:
            exact += 1
            continue
        item = {
            "discipline_id": identifier,
            "code": discipline["code"],
            "name": discipline["name"],
            "differences": differences,
            "active_semester_count": active[identifier],
        }
        if active[identifier] == 0:
            unallocated.append(item)
        else:
            active_mismatches.append(item)
    return {
        "checked": len(disciplines),
        "exact": exact,
        "unallocated_total_without_semester_rows": len(unallocated),
        "active_semester_mismatches": len(active_mismatches),
        "examples": (unallocated + active_mismatches)[:20],
    }
