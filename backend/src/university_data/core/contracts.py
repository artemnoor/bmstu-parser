from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .source_models import (
    SourceAdmissionRequirement,
    SourceCurriculum,
    SourceDepartment,
    SourceFaculty,
    SourceProgram,
    SourceTeacher,
    SourceTuition,
)


class ProviderContractError(TypeError):
    """A provider violated the typed source seam."""


EXPECTED_SOURCE_TYPES: Mapping[str, type[Any]] = {
    "programs": SourceProgram,
    "curricula": SourceCurriculum,
    "faculties": SourceFaculty,
    "departments": SourceDepartment,
    "admission": SourceAdmissionRequirement,
    "tuition": SourceTuition,
    "teachers": SourceTeacher,
}


def validate_provider_output(capability: str, provider: Any, value: Any) -> list[Any]:
    """Validate one provider response before it reaches normalization.

    Failing at this seam prevents the old silent behaviour where an incorrect
    DTO was filtered out with ``isinstance`` and published as an empty
    dataset.  Source keys are part of the provider contract because they are
    the input to canonical stable IDs.
    """

    expected = EXPECTED_SOURCE_TYPES.get(capability)
    if expected is None:
        raise ProviderContractError(f"Unknown provider capability: {capability}")
    declared = getattr(provider, "capability", None)
    if declared != capability:
        raise ProviderContractError(
            f"Provider capability mismatch: expected {capability!r}, got {declared!r}"
        )
    if not isinstance(value, list):
        raise ProviderContractError(
            f"Provider {capability!r} must return list[{expected.__name__}], "
            f"got {type(value).__name__}"
        )

    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, expected):
            raise ProviderContractError(
                f"Provider {capability!r} item {index} must be "
                f"{expected.__name__}, got {type(item).__name__}"
            )
        if not item.source_key.strip():
            raise ProviderContractError(
                f"Provider {capability!r} item {index} has empty source_key"
            )
        if item.source_key in seen:
            raise ProviderContractError(
                f"Provider {capability!r} returned duplicate source_key "
                f"{item.source_key!r}"
            )
        seen.add(item.source_key)
    return value


__all__ = ["EXPECTED_SOURCE_TYPES", "ProviderContractError", "validate_provider_output"]
