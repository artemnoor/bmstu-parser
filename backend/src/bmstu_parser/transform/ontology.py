from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..domain.ids import link_id, stable_id
from ..domain.models import Major, SourceProvenance


def _provenance(value: SourceProvenance) -> dict[str, Any]:
    return asdict(value)


class OntologyBuilder:
    """Build a compact object/link layer over normalized BMSTU records."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, dict[str, Any]]] = {}
        self.links: dict[str, dict[str, Any]] = {}

    def add_object(
        self,
        object_type: str,
        natural_key: Any,
        properties: dict[str, Any],
        provenance: SourceProvenance,
        object_id: str | None = None,
    ) -> str:
        identifier = object_id or stable_id(object_type, natural_key)
        bucket = self.objects.setdefault(object_type, {})
        candidate = {
            "id": identifier,
            "object_type": object_type,
            "properties": properties,
            "provenance": _provenance(provenance),
        }
        existing = bucket.get(identifier)
        if existing is None:
            bucket[identifier] = candidate
        else:
            existing["properties"] = self._merge(existing["properties"], properties)
        return identifier

    def add_link(
        self,
        link_type: str,
        from_id: str,
        to_id: str,
        provenance: SourceProvenance,
        properties: dict[str, Any] | None = None,
    ) -> str:
        identifier = link_id(link_type, from_id, to_id)
        self.links.setdefault(
            identifier,
            {
                "id": identifier,
                "link_type": link_type,
                "from_id": from_id,
                "to_id": to_id,
                "properties": properties or {},
                "provenance": _provenance(provenance),
            },
        )
        return identifier

    @staticmethod
    def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        merged = dict(left)
        for key, value in right.items():
            if value in (None, "", [], {}):
                continue
            if isinstance(value, list) and isinstance(merged.get(key), list):
                merged[key] = list(dict.fromkeys([*merged[key], *value]))
            elif key not in merged or merged[key] in (None, "", [], {}):
                merged[key] = value
        return merged

    def build(self, majors: list[Major]) -> dict[str, Any]:
        for major in majors:
            self._major(major)
        objects = {
            object_type: [bucket[key] for key in sorted(bucket)]
            for object_type, bucket in sorted(self.objects.items())
        }
        links = [self.links[key] for key in sorted(self.links)]
        return {"objects": objects, "links": links}

    def _major(self, major: Major) -> None:
        major_id = self.add_object(
            "major",
            major.slug or major.code,
            {
                "source_key": major.slug,
                "slug": major.slug,
                "code": major.code,
                "name": major.name,
                "qualification": major.qualification,
                "science_degree": major.science_degree,
                "study_period": major.study_period,
                "military": major.military,
                "status": major.status,
            },
            major.provenance,
            object_id=major.id,
        )

        for faculty in major.faculties:
            faculty_id = self.add_object(
                "faculty",
                faculty.slug or faculty.code or faculty.name,
                {
                    "source_key": faculty.slug,
                    "slug": faculty.slug,
                    "code": faculty.code,
                    "name": faculty.name,
                },
                faculty.provenance,
                object_id=faculty.id,
            )
            self.add_link("major_offered_by_faculty", major_id, faculty_id, major.provenance)

        for requirement in major.entrance_requirements:
            requirement_id = self.add_object(
                "entrance_requirement",
                requirement.id,
                {
                    "source_key": requirement.id,
                    "subject": requirement.subject,
                    "minimum_score": requirement.minimum_score,
                    "is_choice": requirement.is_choice,
                    "requirement_type": requirement.requirement_type,
                },
                requirement.provenance,
                object_id=requirement.id,
            )
            self.add_link("major_requires_entrance_subject", major_id, requirement_id, requirement.provenance)

        for tuition in major.tuition:
            tuition_id = self.add_object(
                "tuition_option",
                tuition.id,
                {
                    "source_key": tuition.id,
                    "study_form": tuition.study_form,
                    "value": tuition.value,
                    "discount_value": tuition.discount_value,
                    "currency": tuition.currency,
                    "term": tuition.term,
                    "discount_url": tuition.discount_url,
                    "subtitle": tuition.subtitle,
                },
                tuition.provenance,
                object_id=tuition.id,
            )
            self.add_link("major_has_tuition_option", major_id, tuition_id, tuition.provenance)

        for place in major.places:
            place_id = self.add_object(
                "admission_place",
                place.id,
                {"source_key": place.id, "type": place.place_type, "count": place.count},
                place.provenance,
                object_id=place.id,
            )
            self.add_link("major_has_admission_place", major_id, place_id, place.provenance)

        for score in major.historical_passing_scores:
            score_id = self.add_object(
                "historical_passing_score",
                score.id,
                {
                    "source_key": score.id,
                    "year": score.year,
                    "score": score.score,
                    "department_id": score.department_id,
                    "department_name": score.department_name,
                },
                score.provenance,
                object_id=score.id,
            )
            self.add_link("major_has_historical_passing_score", major_id, score_id, score.provenance)

        for discipline in major.key_disciplines:
            discipline_id = self.add_object(
                "discipline",
                (major.id, discipline),
                {"source_key": discipline, "name": discipline, "scope": "major"},
                major.provenance,
            )
            self.add_link("major_has_discipline", major_id, discipline_id, major.provenance)

        for department in major.departments:
            department_id = self.add_object(
                "department",
                department.slug or department.code or department.name,
                {
                    "source_key": department.slug,
                    "slug": department.slug,
                    "code": department.code,
                    "name": department.name,
                    "faculty_id": department.faculty_id,
                    "faculty_name": department.faculty_name,
                    "realized_programs": department.realized_programs,
                    "short_description": department.short_description,
                    "description": department.description,
                    "practice_description": department.practice_description,
                    "key_disciplines": department.key_disciplines,
                    "phone": department.phone,
                    "address": department.address,
                    "site": department.site,
                },
                department.provenance,
                object_id=department.id,
            )
            self.add_link("major_prepared_by_department", major_id, department_id, department.provenance)
            if department.faculty_id:
                faculty_id = self.add_object(
                    "faculty",
                    department.faculty_id,
                    {"source_key": department.faculty_id, "name": department.faculty_name},
                    department.provenance,
                    object_id=department.faculty_id,
                )
                self.add_link("department_part_of_faculty", department_id, faculty_id, department.provenance)

            for discipline in department.key_disciplines:
                discipline_id = self.add_object(
                    "discipline",
                    (department.id, discipline),
                    {"source_key": discipline, "name": discipline, "scope": "department"},
                    department.provenance,
                )
                self.add_link("department_teaches_discipline", department_id, discipline_id, department.provenance)

            for score in department.historical_passing_scores:
                score_id = self.add_object(
                    "historical_passing_score",
                    score.id,
                    {
                        "source_key": score.id,
                        "year": score.year,
                        "score": score.score,
                        "department_id": score.department_id,
                        "department_name": score.department_name,
                    },
                    score.provenance,
                    object_id=score.id,
                )
                self.add_link("department_has_historical_passing_score", department_id, score_id, score.provenance)

            for program in department.educational_programs:
                self._program(major_id, department_id, program)

    def _program(self, major_id: str, department_id: str, program: Any) -> None:
        program_id = self.add_object(
            "educational_program",
            program.id,
            {
                "source_key": program.id,
                "major_id": program.major_id,
                "department_id": program.department_id,
                "department_name": program.department_name,
                "name": program.name,
                "code": program.code,
                "enrollment_available": program.enrollment_available,
                "location": program.location,
                "description": program.description,
                "disciplines": program.disciplines,
                "study_plan_url": program.study_plan_url,
            },
            program.provenance,
            object_id=program.id,
        )
        self.add_link("major_has_educational_program", major_id, program_id, program.provenance)
        self.add_link("department_runs_program", department_id, program_id, program.provenance)

        for discipline in program.disciplines:
            discipline_id = self.add_object(
                "discipline",
                (program.id, discipline),
                {"source_key": discipline, "name": discipline, "scope": "program"},
                program.provenance,
            )
            self.add_link("program_contains_discipline", program_id, discipline_id, program.provenance)

        if program.study_plan_url or program.study_plan.status != "missing":
            plan_id = self.add_object(
                "study_plan",
                program.id,
                {
                    "source_key": program.id,
                    "url": program.study_plan.url,
                    "resolved_url": program.study_plan.resolved_url,
                    "status": program.study_plan.status,
                    "error": program.study_plan.error,
                },
                program.provenance,
                object_id=stable_id("study-plan", program.id),
            )
            self.add_link("program_has_study_plan", program_id, plan_id, program.provenance)
            for file_info in program.study_plan.files:
                document_id = self.add_object(
                    "study_plan_document",
                    file_info.id,
                    {
                        "source_key": file_info.id,
                        "name": file_info.name,
                        "path": file_info.path,
                        "size": file_info.size,
                        "mime_type": file_info.mime_type,
                        "md5": file_info.md5,
                        "sha256": file_info.sha256,
                        "source_url": file_info.source_url,
                        "resolved_url": file_info.resolved_url,
                        "download_url": file_info.download_url,
                        "local_path": file_info.local_path,
                        "downloaded": file_info.downloaded,
                        "downloaded_size": file_info.downloaded_size,
                        "download_error": file_info.download_error,
                    },
                    program.provenance,
                    object_id=file_info.id,
                )
                self.add_link("study_plan_contains_document", plan_id, document_id, program.provenance)

        for partner in program.practice_partners:
            partner_id = self.add_object(
                "practice_partner",
                partner.id,
                {
                    "source_key": partner.id,
                    "name": partner.name,
                    "url": partner.url,
                    "image": partner.image,
                },
                partner.provenance,
                object_id=partner.id,
            )
            self.add_link("program_has_practice_partner", program_id, partner_id, partner.provenance)

