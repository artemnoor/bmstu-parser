from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from .provenance import SOURCE_FIELDS


@dataclass(frozen=True, slots=True)
class SourceObservation:
    source_page: str = ""
    list_api: str = ""
    detail_api: str = ""
    detail_page: str = ""
    fetched_at_utc: str = ""
    raw_snapshot_path: str = ""
    source_key: str = ""


@dataclass(slots=True)
class SourceProvenance:
    source_page: str = ""
    list_api: str = ""
    detail_api: str = ""
    detail_page: str = ""
    fetched_at_utc: str = ""
    raw_snapshot_path: str = ""
    source_key: str = ""
    sources: list[SourceObservation] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.sources and any(
            getattr(self, field_name) for field_name in SOURCE_FIELDS
        ):
            self.sources.append(
                SourceObservation(
                    source_page=self.source_page,
                    list_api=self.list_api,
                    detail_api=self.detail_api,
                    detail_page=self.detail_page,
                    fetched_at_utc=self.fetched_at_utc,
                    raw_snapshot_path=self.raw_snapshot_path,
                    source_key=self.source_key,
                )
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    minimum_score: int | None
    is_choice: bool | None
    requirement_type: str
    provenance: SourceProvenance
    legacy_id: str = ""
    minimum_score_raw: str = ""
    normalization_warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TuitionOption:
    id: str
    study_form: str
    value: Decimal | None
    discount_value: Decimal | None
    currency: str
    term: str
    discount_url: str
    subtitle: str
    provenance: SourceProvenance
    legacy_id: str = ""
    value_raw: str = ""
    discount_value_raw: str = ""
    normalization_warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AdmissionPlace:
    id: str
    place_type: str
    count: int | None
    provenance: SourceProvenance
    legacy_id: str = ""
    count_raw: str = ""
    normalization_warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class HistoricalPassingScore:
    id: str
    year: int | None
    score: int | None
    department_id: str
    department_name: str
    provenance: SourceProvenance
    legacy_id: str = ""
    year_raw: str = ""
    score_raw: str = ""
    normalization_warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PlanFile:
    id: str
    name: str
    path: str
    size: int | None
    mime_type: str
    md5: str
    sha256: str
    source_url: str
    resolved_url: str
    download_url: str
    local_path: str = ""
    downloaded: bool = False
    downloaded_size: int | None = None
    download_error: str | None = None
    size_raw: str = ""
    normalization_warnings: list[str] = field(default_factory=list)


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
    legacy_id: str = ""


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
