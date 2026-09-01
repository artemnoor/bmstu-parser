from __future__ import annotations

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
    university_id: str, values: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    return {university_id: dict(values)} if values else {}


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

    def program(self, university_id: str, source: SourceProgram) -> Program:
        identifier = global_stable_id(
            university_id, "program", source.source_key or source.code or source.name
        )
        direction_key = source.study_direction_key or source.code or source.name
        department_id = (
            global_stable_id(university_id, "department", source.department_key)
            if source.department_key
            else ""
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
            extensions=_extensions(university_id, source.extensions),
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
            extensions=_extensions(university_id, source.extensions),
            provenance=source.provenance,
        )

    def department(self, university_id: str, source: SourceDepartment) -> Department:
        return Department(
            id=global_stable_id(
                university_id,
                "department",
                source.source_key or source.code or source.name,
            ),
            university_id=university_id,
            name=source.name,
            code=source.code,
            faculty_id=(
                global_stable_id(university_id, "faculty", source.faculty_key)
                if source.faculty_key
                else ""
            ),
            field_meta={
                "name": _published_meta(source.name),
                "code": _published_meta(source.code),
            },
            extensions=_extensions(university_id, source.extensions),
            provenance=source.provenance,
        )

    def curriculum(self, university_id: str, source: SourceCurriculum) -> Curriculum:
        return Curriculum(
            id=global_stable_id(university_id, "curriculum", source.source_key),
            university_id=university_id,
            program_id=(
                global_stable_id(university_id, "program", source.program_key)
                if source.program_key
                else ""
            ),
            name=source.name,
            source_path=str(source.path or ""),
            field_meta={"name": _published_meta(source.name)},
            extensions=_extensions(university_id, source.extensions),
            provenance=source.provenance,
        )

    def discipline(
        self,
        university_id: str,
        source: SourceDiscipline,
        resolution: Resolution[int | float],
    ) -> Discipline:
        return Discipline(
            id=global_stable_id(
                university_id, "discipline", source.source_key or source.name
            ),
            university_id=university_id,
            name=source.name,
            code=source.code,
            curriculum_id=(
                global_stable_id(university_id, "curriculum", source.curriculum_key)
                if source.curriculum_key
                else ""
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
            extensions=_extensions(university_id, source.extensions),
            provenance=source.provenance,
        )

    def teacher(self, university_id: str, source: SourceTeacher) -> Teacher:
        return Teacher(
            id=global_stable_id(
                university_id, "teacher", source.source_key or source.name
            ),
            university_id=university_id,
            name=source.name,
            position=source.position,
            department_id=(
                global_stable_id(university_id, "department", source.department_key)
                if source.department_key
                else ""
            ),
            email=source.email,
            field_meta={"name": _published_meta(source.name)},
            extensions=_extensions(university_id, source.extensions),
            provenance=source.provenance,
        )

    def semester(self, university_id: str, source: SourceSemester) -> Semester:
        return Semester(
            id=global_stable_id(university_id, "semester", source.number),
            university_id=university_id,
            number=source.number,
            field_meta={"number": _published_meta(source.number)},
            extensions=_extensions(university_id, source.extensions),
            provenance=source.provenance,
        )

    def semester_load(
        self, university_id: str, source: SourceSemesterLoad
    ) -> SemesterLoad:
        discipline_id = (
            global_stable_id(university_id, "discipline", source.discipline_key)
            if source.discipline_key
            else ""
        )
        semester_id = global_stable_id(university_id, "semester", source.semester)
        curriculum_id = (
            global_stable_id(university_id, "curriculum", source.curriculum_key)
            if source.curriculum_key
            else ""
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
            extensions=_extensions(university_id, source.extensions),
            provenance=source.provenance,
        )

    def admission(
        self, university_id: str, source: SourceAdmissionRequirement
    ) -> AdmissionRequirement:
        return AdmissionRequirement(
            id=global_stable_id(
                university_id,
                "admission_requirement",
                source.source_key or source.subject,
            ),
            university_id=university_id,
            subject=source.subject,
            program_id=(
                global_stable_id(university_id, "program", source.program_key)
                if source.program_key
                else ""
            ),
            study_direction_id=(
                global_stable_id(
                    university_id, "study_direction", source.study_direction_key
                )
                if source.study_direction_key
                else ""
            ),
            minimum_score=source.minimum_score,
            is_choice=source.is_choice,
            field_meta={"minimum_score": _published_meta(source.minimum_score)},
            extensions=_extensions(university_id, source.extensions),
            provenance=source.provenance,
        )

    def tuition(self, university_id: str, source: SourceTuition) -> TuitionOption:
        value = _decimal_or_none(source.value)
        return TuitionOption(
            id=global_stable_id(
                university_id,
                "tuition_option",
                source.source_key or source.study_form,
            ),
            university_id=university_id,
            study_form=source.study_form,
            program_id=(
                global_stable_id(university_id, "program", source.program_key)
                if source.program_key
                else ""
            ),
            study_direction_id=(
                global_stable_id(
                    university_id, "study_direction", source.study_direction_key
                )
                if source.study_direction_key
                else ""
            ),
            value=value,
            currency=source.currency,
            term=source.term,
            field_meta={"value": _published_meta(value)},
            extensions=_extensions(university_id, source.extensions),
            provenance=source.provenance,
        )

    @staticmethod
    def source_dict(source: Any) -> dict[str, Any]:
        return (
            asdict(source) if hasattr(source, "__dataclass_fields__") else dict(source)
        )
