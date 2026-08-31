from __future__ import annotations

from dataclasses import dataclass, fields

CAPABILITY_NAMES = (
    "programs",
    "curricula",
    "faculties",
    "departments",
    "admission",
    "tuition",
    "teachers",
)


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
