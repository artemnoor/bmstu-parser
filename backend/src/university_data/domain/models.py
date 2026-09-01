from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from .provenance import FieldMeta, SourceProvenance


class _Canonical:
    university_id: str
    field_meta: dict[str, FieldMeta]
    extensions: dict[str, dict[str, Any]]
    provenance: SourceProvenance

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]


@dataclass(slots=True)
class University(_Canonical):
    id: str
    university_id: str
    name: str
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)


@dataclass(slots=True)
class StudyDirection(_Canonical):
    id: str
    university_id: str
    name: str
    code: str = ""
    status: str = ""
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)


@dataclass(slots=True)
class Program(_Canonical):
    id: str
    university_id: str
    study_direction_id: str
    name: str
    code: str = ""
    department_id: str = ""
    description: str = ""
    study_plan_url: str = ""
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)


@dataclass(slots=True)
class Faculty(_Canonical):
    id: str
    university_id: str
    name: str
    code: str = ""
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)


@dataclass(slots=True)
class Department(_Canonical):
    id: str
    university_id: str
    name: str
    faculty_id: str = ""
    code: str = ""
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)


@dataclass(slots=True)
class Curriculum(_Canonical):
    id: str
    university_id: str
    program_id: str
    name: str = ""
    source_path: str = ""
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)


@dataclass(slots=True)
class Discipline(_Canonical):
    id: str
    university_id: str
    name: str
    code: str = ""
    curriculum_id: str = ""
    total_hours: int | float | None = None
    credits: int | float | None = None
    semester: int | str | None = None
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)


@dataclass(slots=True)
class Teacher(_Canonical):
    id: str
    university_id: str
    name: str
    position: str = ""
    department_id: str = ""
    email: str = ""
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)


@dataclass(slots=True)
class Semester(_Canonical):
    id: str
    university_id: str
    number: int
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)


@dataclass(slots=True)
class SemesterLoad(_Canonical):
    id: str
    university_id: str
    discipline_id: str
    semester_id: str
    curriculum_id: str = ""
    hours: int | float | None = None
    credits: int | float | None = None
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)


@dataclass(slots=True)
class AdmissionRequirement(_Canonical):
    id: str
    university_id: str
    subject: str
    program_id: str = ""
    study_direction_id: str = ""
    minimum_score: int | None = None
    is_choice: bool | None = None
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)


@dataclass(slots=True)
class TuitionOption(_Canonical):
    id: str
    university_id: str
    study_form: str
    program_id: str = ""
    study_direction_id: str = ""
    value: Decimal | None = None
    currency: str = ""
    term: str = ""
    field_meta: dict[str, FieldMeta] = field(default_factory=dict)
    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    provenance: SourceProvenance = field(default_factory=SourceProvenance)
