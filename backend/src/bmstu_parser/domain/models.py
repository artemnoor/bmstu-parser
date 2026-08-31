from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SourceProvenance:
    source_page: str = ""
    list_api: str = ""
    detail_api: str = ""
    detail_page: str = ""
    fetched_at_utc: str = ""
    raw_snapshot_path: str = ""
    source_key: str = ""


@dataclass(slots=True)
class Faculty:
    id: str
    slug: str
    code: str
    name: str
    provenance: SourceProvenance


@dataclass(slots=True)
class EntranceRequirement:
    id: str
    subject: str
    minimum_score: Any
    is_choice: bool | None
    requirement_type: str
    provenance: SourceProvenance


@dataclass(slots=True)
class TuitionOption:
    id: str
    study_form: str
    value: Any
    discount_value: Any
    currency: str
    term: str
    discount_url: str
    subtitle: str
    provenance: SourceProvenance


@dataclass(slots=True)
class AdmissionPlace:
    id: str
    place_type: str
    count: Any
    provenance: SourceProvenance


@dataclass(slots=True)
class HistoricalPassingScore:
    id: str
    year: Any
    score: Any
    department_id: str
    department_name: str
    provenance: SourceProvenance


@dataclass(slots=True)
class PlanFile:
    id: str
    name: str
    path: str
    size: Any
    mime_type: str
    md5: str
    sha256: str
    source_url: str
    resolved_url: str
    download_url: str
    local_path: str = ""
    downloaded: bool = False
    downloaded_size: Any = None
    download_error: str | None = None


@dataclass(slots=True)
class StudyPlan:
    url: str
    status: str
    files: list[PlanFile] = field(default_factory=list)
    error: str | None = None
    resolved_url: str = ""


@dataclass(slots=True)
class PracticePartner:
    id: str
    name: str
    url: str
    image: str
    provenance: SourceProvenance


@dataclass(slots=True)
class EducationalProgram:
    id: str
    major_id: str
    department_id: str
    department_name: str
    name: str
    code: str
    enrollment_available: bool | None
    location: str
    description: str
    disciplines: list[str]
    study_plan_url: str
    study_plan: StudyPlan
    practice_partners: list[PracticePartner]
    provenance: SourceProvenance


@dataclass(slots=True)
class Department:
    id: str
    slug: str
    code: str
    name: str
    faculty_id: str
    faculty_name: str
    realized_programs: list[str]
    short_description: str
    description: str
    practice_description: str
    key_disciplines: list[str]
    historical_passing_scores: list[HistoricalPassingScore]
    educational_programs: list[EducationalProgram]
    phone: str
    address: str
    site: str
    provenance: SourceProvenance


@dataclass(slots=True)
class Major:
    id: str
    status: str
    detail_error: str | None
    slug: str
    name: str
    code: str
    qualification: str
    science_degree: str
    study_period: str
    military: bool | None
    description: str
    faculties: list[Faculty]
    faculty_id: str
    faculty_name: str
    tuition: list[TuitionOption]
    entrance_requirements: list[EntranceRequirement]
    places: list[AdmissionPlace]
    historical_passing_scores: list[HistoricalPassingScore]
    key_disciplines: list[str]
    departments: list[Department]
    educational_programs: list[EducationalProgram]
    specializations: list[str]
    provenance: SourceProvenance

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

