from __future__ import annotations

from .capabilities import CAPABILITY_NAMES, CapabilityDefinition
from .source_models import (
    SourceAdmissionRequirement,
    SourceCurriculum,
    SourceDepartment,
    SourceFaculty,
    SourceProgram,
    SourceTeacher,
    SourceTuition,
)

CORE_CAPABILITY_DEFINITIONS: dict[str, CapabilityDefinition] = {
    "programs": CapabilityDefinition(
        "programs",
        SourceProgram,
        "programs",
        ("programs", "study_directions"),
        "program",
        "_programs",
        ("programs", "study_directions"),
        (
            ("study_direction_id", "programs"),
            ("department_id", "departments"),
        ),
    ),
    "curricula": CapabilityDefinition(
        "curricula",
        SourceCurriculum,
        "curricula",
        ("curricula", "disciplines", "semesters", "semester_loads"),
        "curriculum",
        "_curricula",
        ("curricula", "semantic_disciplines", "semantic_semester_loads"),
        (
            ("program_id", "programs"),
            ("curriculum_id", "curricula"),
            ("discipline_id", "curricula"),
            ("semester_id", "curricula"),
        ),
        quality_checks=(
            "records_university_scoped",
            "provenance_present",
            "record_ids_unique",
            "record_ids_present",
            "orphan_links",
            "semantic_study_plans",
        ),
    ),
    "faculties": CapabilityDefinition(
        "faculties",
        SourceFaculty,
        "faculties",
        ("faculties",),
        "faculty",
        "_faculties",
        ("faculties",),
    ),
    "departments": CapabilityDefinition(
        "departments",
        SourceDepartment,
        "departments",
        ("departments",),
        "department",
        "_departments",
        ("departments",),
        (("faculty_id", "faculties"),),
    ),
    "admission": CapabilityDefinition(
        "admission",
        SourceAdmissionRequirement,
        "admission_requirements",
        ("admission_requirements",),
        "admission_requirement",
        "_admission",
        ("admission", "admission_requirements"),
        (
            ("program_id", "programs"),
            ("study_direction_id", "programs"),
        ),
    ),
    "tuition": CapabilityDefinition(
        "tuition",
        SourceTuition,
        "tuition_options",
        ("tuition_options",),
        "tuition_option",
        "_tuition",
        ("tuition_options",),
        (
            ("program_id", "programs"),
            ("study_direction_id", "programs"),
        ),
    ),
    "teachers": CapabilityDefinition(
        "teachers",
        SourceTeacher,
        "teachers",
        ("teachers",),
        "teacher",
        "_teachers",
        ("teachers",),
        (("department_id", "departments"),),
    ),
}

if tuple(CORE_CAPABILITY_DEFINITIONS) != CAPABILITY_NAMES:
    raise RuntimeError("Core capability registry is out of sync with capability names")


RELATION_CAPABILITIES = {
    field_name: target_capability
    for definition in CORE_CAPABILITY_DEFINITIONS.values()
    for field_name, target_capability in definition.relations
}


def capability_definition(name: str) -> CapabilityDefinition:
    try:
        return CORE_CAPABILITY_DEFINITIONS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown university capability: {name}") from exc


def dataset_capabilities() -> dict[str, str]:
    return {
        dataset: definition.name
        for definition in CORE_CAPABILITY_DEFINITIONS.values()
        for dataset in definition.api_names
    }


__all__ = [
    "CORE_CAPABILITY_DEFINITIONS",
    "RELATION_CAPABILITIES",
    "capability_definition",
    "dataset_capabilities",
]
