from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from typing import Any

from ..core.source_models import (
    SourceAdmissionRequirement,
    SourceCurriculum,
    SourceDepartment,
    SourceDiscipline,
    SourceFaculty,
    SourceProgram,
    SourceSemester,
    SourceSemesterLoad,
    SourceTeacher,
    SourceTuition,
)
from ..domain.ids import global_stable_id
from ..domain.models import (
    AdmissionRequirement,
    Curriculum,
    Department,
    Discipline,
    Faculty,
    Program,
    Semester,
    SemesterLoad,
    StudyDirection,
    Teacher,
    TuitionOption,
    University,
)
from ..domain.provenance import FieldMeta, SourceProvenance
from ..resolvers.engine import Resolution


def _extensions(
    university_id: str,
    values: dict[str, Any],
    legacy_ids: tuple[str, ...] = (),
    unresolved_references: Mapping[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    result = dict(values)
    if legacy_ids:
        result["legacy_ids"] = list(legacy_ids)
    if unresolved_references:
        existing = result.get("unresolved_references", {})
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged.update(unresolved_references)
        result["unresolved_references"] = merged
    return {university_id: result} if result else {}


def _relation_id(
    university_id: str,
    entity_type: str,
    source_key: str,
    capability: str,
    available_capabilities: Mapping[str, bool] | None,
    unresolved_references: dict[str, str],
    field_name: str,
) -> str:
    if not source_key:
        return ""
    if available_capabilities is not None and not available_capabilities.get(
        capability, False
    ):
        unresolved_references[field_name] = source_key
        return ""
    return global_stable_id(university_id, entity_type, source_key)


def _published_meta(value: Any) -> FieldMeta:
    return FieldMeta(
        "published" if value not in (None, "") else "not_published",
        "source",
        1.0 if value not in (None, "") else 0.0,
    )


def _decimal_or_none(value: str | float | None) -> Decimal | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class CanonicalNormalizer:
    """Materialize typed canonical domain models from source DTOs."""

    def university(
        self, university_id: str, name: str, provenance: SourceProvenance
    ) -> University:
        return University(
            id=global_stable_id(university_id, "university", university_id),
            university_id=university_id,
            name=name,
            field_meta={"name": _published_meta(name)},
            extensions={},
            provenance=provenance,
        )

    def study_direction(
        self,
        university_id: str,
        *,
        key: str,
        name: str,
        code: str,
        provenance: SourceProvenance,
    ) -> StudyDirection:
        return StudyDirection(
            id=global_stable_id(university_id, "study_direction", key),
            university_id=university_id,
            name=name,
            code=code,
            field_meta={"name": _published_meta(name), "code": _published_meta(code)},
            extensions={},
            provenance=provenance,
        )

    def program(
        self,
        university_id: str,
        source: SourceProgram,
        *,
        available_capabilities: Mapping[str, bool] | None = None,
    ) -> Program:
        unresolved: dict[str, str] = {}
        identifier = global_stable_id(
            university_id, "program", source.source_key or source.code or source.name
        )
        direction_key = source.study_direction_key or source.code or source.name
        department_id = _relation_id(
            university_id,
            "department",
            source.department_key,
            "departments",
            available_capabilities,
            unresolved,
            "department_key",
        )
        return Program(
            id=identifier,
            university_id=university_id,
            study_direction_id=global_stable_id(
                university_id, "study_direction", direction_key
            ),
            name=source.name,
            code=source.code,
            department_id=department_id,
            description=source.description,
            study_plan_url=source.study_plan_url,
            field_meta={
                "name": _published_meta(source.name),
                "code": _published_meta(source.code),
            },
            extensions=_extensions(
                university_id,
                source.extensions,
                source.legacy_ids,
                unresolved,
            ),
            provenance=source.provenance,
        )

    def faculty(self, university_id: str, source: SourceFaculty) -> Faculty:
        return Faculty(
            id=global_stable_id(
                university_id,
                "faculty",
                source.source_key or source.code or source.name,
            ),
            university_id=university_id,
            name=source.name,
            code=source.code,
            field_meta={
                "name": _published_meta(source.name),
                "code": _published_meta(source.code),
            },
            extensions=_extensions(university_id, source.extensions, source.legacy_ids),
            provenance=source.provenance,
        )

    def department(
        self,
        university_id: str,
        source: SourceDepartment,
        *,
        available_capabilities: Mapping[str, bool] | None = None,
    ) -> Department:
        unresolved: dict[str, str] = {}
        return Department(
            id=global_stable_id(
                university_id,
                "department",
                source.source_key or source.code or source.name,
            ),
            university_id=university_id,
            name=source.name,
            code=source.code,
            faculty_id=_relation_id(
                university_id,
                "faculty",
                source.faculty_key,
                "faculties",
                available_capabilities,
                unresolved,
                "faculty_key",
            ),
            field_meta={
                "name": _published_meta(source.name),
                "code": _published_meta(source.code),
            },
            extensions=_extensions(
                university_id,
                source.extensions,
                source.legacy_ids,
                unresolved,
            ),
            provenance=source.provenance,
        )

    def curriculum(
        self,
        university_id: str,
        source: SourceCurriculum,
        *,
        available_capabilities: Mapping[str, bool] | None = None,
    ) -> Curriculum:
        unresolved: dict[str, str] = {}
        return Curriculum(
            id=global_stable_id(university_id, "curriculum", source.source_key),
            university_id=university_id,
            program_id=_relation_id(
                university_id,
                "program",
                source.program_key,
                "programs",
                available_capabilities,
                unresolved,
                "program_key",
            ),
            name=source.name,
            source_path=str(source.path or ""),
            field_meta={"name": _published_meta(source.name)},
            extensions=_extensions(
                university_id,
                source.extensions,
                source.legacy_ids,
                unresolved,
            ),
            provenance=source.provenance,
        )

    def discipline(
        self,
        university_id: str,
        source: SourceDiscipline,
        resolution: Resolution[int | float],
        *,
        available_capabilities: Mapping[str, bool] | None = None,
    ) -> Discipline:
        unresolved: dict[str, str] = {}
        return Discipline(
            id=global_stable_id(
                university_id, "discipline", source.source_key or source.name
            ),
            university_id=university_id,
            name=source.name,
            code=source.code,
            curriculum_id=_relation_id(
                university_id,
                "curriculum",
                source.curriculum_key,
                "curricula",
                available_capabilities,
                unresolved,
                "curriculum_key",
            ),
            total_hours=resolution.value,
            credits=source.credits,
            semester=source.semester,
            field_meta={
                "total_hours": FieldMeta(
                    resolution.status,
                    resolution.method,
                    resolution.confidence,
                    sources=resolution.sources,
                    warnings=resolution.warnings,
                )
            },
            extensions=_extensions(
                university_id,
                source.extensions,
                source.legacy_ids,
                unresolved,
            ),
            provenance=source.provenance,
        )

    def teacher(
        self,
        university_id: str,
        source: SourceTeacher,
        *,
        available_capabilities: Mapping[str, bool] | None = None,
    ) -> Teacher:
        unresolved: dict[str, str] = {}
        return Teacher(
            id=global_stable_id(
                university_id, "teacher", source.source_key or source.name
            ),
            university_id=university_id,
            name=source.name,
            position=source.position,
            department_id=_relation_id(
                university_id,
                "department",
                source.department_key,
                "departments",
                available_capabilities,
                unresolved,
                "department_key",
            ),
            email=source.email,
            field_meta={"name": _published_meta(source.name)},
            extensions=_extensions(
                university_id,
                source.extensions,
                source.legacy_ids,
                unresolved,
            ),
            provenance=source.provenance,
        )

    def semester(self, university_id: str, source: SourceSemester) -> Semester:
        return Semester(
            id=global_stable_id(university_id, "semester", source.number),
            university_id=university_id,
            number=source.number,
            field_meta={"number": _published_meta(source.number)},
            extensions=_extensions(university_id, source.extensions, source.legacy_ids),
            provenance=source.provenance,
        )

    def semester_load(
        self,
        university_id: str,
        source: SourceSemesterLoad,
        *,
        available_capabilities: Mapping[str, bool] | None = None,
    ) -> SemesterLoad:
        unresolved: dict[str, str] = {}
        discipline_id = _relation_id(
            university_id,
            "discipline",
            source.discipline_key,
            "curricula",
            available_capabilities,
            unresolved,
            "discipline_key",
        )
        semester_id = global_stable_id(university_id, "semester", source.semester)
        curriculum_id = _relation_id(
            university_id,
            "curriculum",
            source.curriculum_key,
            "curricula",
            available_capabilities,
            unresolved,
            "curriculum_key",
        )
        return SemesterLoad(
            id=global_stable_id(
                university_id, "semester_load", source.discipline_key, source.semester
            ),
            university_id=university_id,
            discipline_id=discipline_id,
            semester_id=semester_id,
            curriculum_id=curriculum_id,
            hours=source.hours,
            credits=source.credits,
            field_meta={
                "hours": _published_meta(source.hours),
                "credits": _published_meta(source.credits),
            },
            extensions=_extensions(
                university_id,
                source.extensions,
                source.legacy_ids,
                unresolved,
            ),
            provenance=source.provenance,
        )

    def admission(
        self,
        university_id: str,
        source: SourceAdmissionRequirement,
        *,
        available_capabilities: Mapping[str, bool] | None = None,
    ) -> AdmissionRequirement:
        unresolved: dict[str, str] = {}
        return AdmissionRequirement(
            id=global_stable_id(
                university_id,
                "admission_requirement",
                source.source_key or source.subject,
            ),
            university_id=university_id,
            subject=source.subject,
            program_id=_relation_id(
                university_id,
                "program",
                source.program_key,
                "programs",
                available_capabilities,
                unresolved,
                "program_key",
            ),
            study_direction_id=_relation_id(
                university_id,
                "study_direction",
                source.study_direction_key,
                "programs",
                available_capabilities,
                unresolved,
                "study_direction_key",
            ),
            minimum_score=source.minimum_score,
            is_choice=source.is_choice,
            field_meta={"minimum_score": _published_meta(source.minimum_score)},
            extensions=_extensions(
                university_id,
                source.extensions,
                source.legacy_ids,
                unresolved,
            ),
            provenance=source.provenance,
        )

    def tuition(
        self,
        university_id: str,
        source: SourceTuition,
        *,
        available_capabilities: Mapping[str, bool] | None = None,
    ) -> TuitionOption:
        unresolved: dict[str, str] = {}
        value = _decimal_or_none(source.value)
        return TuitionOption(
            id=global_stable_id(
                university_id,
                "tuition_option",
                source.source_key or source.study_form,
            ),
            university_id=university_id,
            study_form=source.study_form,
            program_id=_relation_id(
                university_id,
                "program",
                source.program_key,
                "programs",
                available_capabilities,
                unresolved,
                "program_key",
            ),
            study_direction_id=_relation_id(
                university_id,
                "study_direction",
                source.study_direction_key,
                "programs",
                available_capabilities,
                unresolved,
                "study_direction_key",
            ),
            value=value,
            currency=source.currency,
            term=source.term,
            field_meta={"value": _published_meta(value)},
            extensions=_extensions(
                university_id,
                source.extensions,
                source.legacy_ids,
                unresolved,
            ),
            provenance=source.provenance,
        )

    @staticmethod
    def source_dict(source: Any) -> dict[str, Any]:
        return (
            asdict(source) if hasattr(source, "__dataclass_fields__") else dict(source)
        )
