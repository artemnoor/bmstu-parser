from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Literal

CAPABILITY_NAMES = (
    "programs",
    "curricula",
    "faculties",
    "departments",
    "admission",
    "tuition",
    "teachers",
)

CapabilityName = Literal[
    "programs",
    "curricula",
    "faculties",
    "departments",
    "admission",
    "tuition",
    "teachers",
]

CapabilityMode = Literal["not_supported", "enabled"]


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """Static capability declaration owned by a university module."""

    name: str
    mode: CapabilityMode = "not_supported"
    allow_partial: bool = False

    def __post_init__(self) -> None:
        if self.name not in CAPABILITY_NAMES:
            raise ValueError(f"Unknown university capability: {self.name}")
        if self.mode not in {"not_supported", "enabled"}:
            raise ValueError(f"Unknown capability mode: {self.mode}")
        if self.allow_partial and not self.enabled:
            raise ValueError(
                f"Capability {self.name!r} cannot allow partial data when disabled"
            )

    @property
    def enabled(self) -> bool:
        return self.mode == "enabled"


CapabilityStatus = Literal[
    "not_supported", "published", "degraded", "failed", "not_published"
]


@dataclass(frozen=True, slots=True)
class UniversityCapabilities:
    programs: bool = False
    curricula: bool = False
    faculties: bool = False
    departments: bool = False
    admission: bool = False
    tuition: bool = False
    teachers: bool = False

    def supports(self, capability: str) -> bool:
        if capability not in CAPABILITY_NAMES:
            raise ValueError(f"Unknown university capability: {capability}")
        return bool(getattr(self, capability))

    def as_dict(self) -> dict[str, bool]:
        return {item.name: bool(getattr(self, item.name)) for item in fields(self)}

    def supported(self) -> tuple[str, ...]:
        return tuple(name for name in CAPABILITY_NAMES if self.supports(name))

    def specs(
        self, *, allow_partial: set[str] | None = None
    ) -> tuple[CapabilitySpec, ...]:
        partial = allow_partial or set()
        return tuple(
            CapabilitySpec(
                name=name,
                mode="enabled" if self.supports(name) else "not_supported",
                allow_partial=name in partial,
            )
            for name in CAPABILITY_NAMES
        )


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    """The single neutral description shared by all platform layers."""

    name: str
    source_type: type[Any]
    primary_dataset: str
    datasets: tuple[str, ...]
    ontology_type: str
    materializer: str
    api_names: tuple[str, ...]
    relations: tuple[tuple[str, str], ...] = ()
    quality_checks: tuple[str, ...] = (
        "records_university_scoped",
        "provenance_present",
        "record_ids_unique",
        "record_ids_present",
        "orphan_links",
    )

    def __post_init__(self) -> None:
        if self.name not in CAPABILITY_NAMES:
            raise ValueError(f"Unknown university capability: {self.name}")


def capability_specs(
    capabilities: UniversityCapabilities,
    *,
    allow_partial: set[str] | None = None,
) -> tuple[CapabilitySpec, ...]:
    return capabilities.specs(allow_partial=allow_partial)
