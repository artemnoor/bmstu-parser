from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..domain.provenance import (
    SourceProvenance,
    provenance_has_lineage,
    provenance_has_source_locator,
    provenance_source_key,
)
from .capability_registry import CORE_CAPABILITY_DEFINITIONS
from .plugin import DataGap, ProviderResult


class ProviderContractError(TypeError):
    """A provider violated the typed source seam."""


EXPECTED_SOURCE_TYPES: Mapping[str, type[Any]] = {
    name: definition.source_type
    for name, definition in CORE_CAPABILITY_DEFINITIONS.items()
}


def _validate_provenance(
    item: Any, *, capability: str, index: int, persists_raw: bool
) -> None:
    provenance = item.provenance
    if not isinstance(provenance, SourceProvenance):
        raise ProviderContractError(
            f"Provider {capability!r} item {index} must carry SourceProvenance"
        )
    source_key = provenance_source_key(provenance)
    if source_key != item.source_key.strip():
        raise ProviderContractError(
            f"Provider {capability!r} item {index} provenance source_key must match "
            "the DTO source_key"
        )
    if not provenance_has_source_locator(provenance):
        raise ProviderContractError(
            f"Provider {capability!r} item {index} must carry a real source URL/page"
        )
    if persists_raw and not provenance_has_lineage(provenance):
        raise ProviderContractError(
            f"Provider {capability!r} item {index} must carry raw snapshot lineage"
        )
    legacy_ids = getattr(item, "legacy_ids", ())
    if not isinstance(legacy_ids, tuple) or not all(
        isinstance(value, str) and value.strip() for value in legacy_ids
    ):
        raise ProviderContractError(
            f"Provider {capability!r} item {index} has invalid legacy_ids"
        )


def _as_provider_result(value: Any) -> ProviderResult[Any]:
    if isinstance(value, ProviderResult):
        return value
    if isinstance(value, list):
        return ProviderResult(records=tuple(value))
    raise ProviderContractError(
        "Provider must return a list or ProviderResult with source records"
    )


def validate_provider_result(
    capability: str, provider: Any, value: Any
) -> ProviderResult[Any]:
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
    result = _as_provider_result(value)

    if not isinstance(result.records, tuple):
        raise ProviderContractError(
            f"Provider {capability!r} records must be a tuple in ProviderResult"
        )
    seen: set[str] = set()
    persists_raw = bool(getattr(provider, "persists_raw", False))
    for index, item in enumerate(result.records):
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
        _validate_provenance(
            item,
            capability=capability,
            index=index,
            persists_raw=persists_raw,
        )
    if not isinstance(result.warnings, tuple) or not all(
        isinstance(item, str) and item.strip() for item in result.warnings
    ):
        raise ProviderContractError(
            f"Provider {capability!r} warnings must be a tuple of non-empty strings"
        )
    if not isinstance(result.gaps, tuple) or not all(
        isinstance(item, DataGap)
        and bool(item.code.strip())
        and bool(item.message.strip())
        and isinstance(item.source_key, str)
        for item in result.gaps
    ):
        raise ProviderContractError(
            f"Provider {capability!r} gaps must be a tuple of DataGap values"
        )
    if not isinstance(result.complete, bool):
        raise ProviderContractError(f"Provider {capability!r} complete must be boolean")
    if not result.complete and not (result.warnings or result.gaps):
        raise ProviderContractError(
            f"Provider {capability!r} partial result must include warnings or gaps"
        )
    return result


def validate_provider_output(capability: str, provider: Any, value: Any) -> list[Any]:
    """Backward-compatible list-returning wrapper around result validation."""

    return list(validate_provider_result(capability, provider, value).records)


__all__ = [
    "EXPECTED_SOURCE_TYPES",
    "ProviderContractError",
    "validate_provider_output",
    "validate_provider_result",
]
