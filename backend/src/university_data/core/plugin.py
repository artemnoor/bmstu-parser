from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .capabilities import UniversityCapabilities


@dataclass(frozen=True, slots=True)
class UniversityConfig:
    """Validated runtime configuration exposed by a university adapter."""

    university_id: str
    display_name: str
    config_path: Path | None = None
    settings: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SourceProvider(Protocol):
    capability: str

    def fetch(self) -> list[Any]: ...


@dataclass(frozen=True, slots=True)
class UniversityProviders:
    programs: SourceProvider | None = None
    curricula: SourceProvider | None = None
    faculties: SourceProvider | None = None
    departments: SourceProvider | None = None
    admission: SourceProvider | None = None
    tuition: SourceProvider | None = None
    teachers: SourceProvider | None = None

    def for_capability(self, capability: str) -> SourceProvider | None:
        return getattr(self, capability, None)


@runtime_checkable
class UniversityPlugin(Protocol):
    university_id: str
    display_name: str

    def capabilities(self) -> UniversityCapabilities: ...

    def providers(self) -> UniversityProviders: ...

    def config(self) -> UniversityConfig: ...
