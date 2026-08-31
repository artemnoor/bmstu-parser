from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.provenance import SourceProvenance


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_key: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)


@dataclass(frozen=True, slots=True)
class SourceProgram(SourceRecord):
    name: str = ""
    code: str = ""
    study_direction_key: str = ""
    department_key: str = ""
    description: str = ""
    study_plan_url: str = ""


@dataclass(frozen=True, slots=True)
class SourceFaculty(SourceRecord):
    name: str = ""
    code: str = ""


@dataclass(frozen=True, slots=True)
class SourceDepartment(SourceRecord):
    name: str = ""
    code: str = ""
    faculty_key: str = ""


@dataclass(frozen=True, slots=True)
class SourceAdmissionRequirement(SourceRecord):
    subject: str = ""
    minimum_score: int | None = None
    is_choice: bool | None = None


@dataclass(frozen=True, slots=True)
class SourceTuition(SourceRecord):
    study_form: str = ""
    value: str | int | float | None = None
    currency: str = ""
    term: str = ""


@dataclass(frozen=True, slots=True)
class SourceCurriculum(SourceRecord):
    name: str = ""
    program_key: str = ""
    path: Path | None = None
    rows: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class SourceDiscipline(SourceRecord):
    name: str = ""
    code: str = ""
    total_hours: int | float | None = None
    credits: int | float | None = None
    components: dict[str, int | float | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceTeacher(SourceRecord):
    name: str = ""
    position: str = ""
    department_key: str = ""
    email: str = ""
