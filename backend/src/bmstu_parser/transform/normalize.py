from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import quote

from ..config import DETAIL_ENDPOINT, LIST_ENDPOINT, SITE_BASE, SOURCE_PAGE
from ..domain.ids import deterministic_record_ids, stable_id
from ..domain.models import (
    AdmissionPlace,
    Department,
    EducationalProgram,
    EntranceRequirement,
    Faculty,
    HistoricalPassingScore,
    Major,
    PracticePartner,
    SourceProvenance,
    StudyPlan,
    TuitionOption,
)
from ..domain.types import parse_decimal, parse_int
from ..ingestion.mirror_api import DetailFetch
from .text import as_list, bool_or_none, clean_text, first_text, normalize_url


class Normalizer:
    """Convert source-shaped API payloads into the canonical domain model."""

    def normalize(self, fetched: DetailFetch) -> Major:
        summary = fetched.summary
        detail = fetched.detail if isinstance(fetched.detail, dict) else {}
        slug = first_text(summary.get("slug"), detail.get("slug"))
        detail_api = DETAIL_ENDPOINT.format(slug=quote(slug, safe="")) if slug else ""
        provenance = SourceProvenance(
            source_page=SOURCE_PAGE,
            list_api=LIST_ENDPOINT,
            detail_api=detail_api,
            detail_page=f"{SITE_BASE}/bachelor/majors/{quote(slug, safe='')}"
            if slug
            else "",
            fetched_at_utc=fetched.fetched_at_utc,
            raw_snapshot_path=f"raw/details/{slug}.json" if slug else "",
            source_key=slug,
        )

        faculties = self._faculties(summary, provenance)
        summary_departments = self._summary_departments(summary, faculties, provenance)
        detail_departments = self._departments(detail, slug, provenance)
        departments = detail_departments or summary_departments

        additional = (
            detail.get("additional")
            if isinstance(detail.get("additional"), dict)
            else {}
        )
        detail_faculty = (
            detail.get("faculty") if isinstance(detail.get("faculty"), dict) else {}
        )
        fallback_faculty = faculties[0] if faculties else None
        faculty_id = self._faculty_id(detail_faculty, fallback_faculty, slug)
        faculty_name = clean_text(
            detail_faculty.get("title")
            if detail_faculty
            else (fallback_faculty.name if fallback_faculty else "")
        )

        point_entries = [
            (index, item)
            for index, item in enumerate(as_list(detail.get("points")))
            if isinstance(item, dict)
        ]
        point_items = [item for _index, item in point_entries]
        requirement_ids = deterministic_record_ids(
            "entrance-requirement",
            point_items,
            key=lambda item: (
                first_text(item.get("id"), item.get("code"), item.get("title")),
                bool_or_none(item.get("isChoice")),
            ),
            legacy_key=lambda item, index: (slug, item.get("title"), index),
            legacy_indices=[index for index, _item in point_entries],
        )
        current_requirements = [
            self._entrance_requirement(item, slug, identifier, legacy_id, provenance)
            for item, (identifier, legacy_id) in zip(
                point_items, requirement_ids, strict=True
            )
        ]

        tuition_entries = [
            (index, item)
            for index, item in enumerate(as_list(detail.get("price")))
            if isinstance(item, dict)
        ]
        tuition_items = [item for _index, item in tuition_entries]
        tuition_ids = deterministic_record_ids(
            "tuition-option",
            tuition_items,
            key=lambda item: (
                first_text(item.get("id"), item.get("code")),
                item.get("studyForm"),
                item.get("term"),
            ),
            legacy_key=lambda item, index: (
                slug,
                item.get("studyForm"),
                item.get("term"),
                index,
            ),
            legacy_indices=[index for index, _item in tuition_entries],
        )
        tuition = [
            self._tuition(item, slug, identifier, legacy_id, provenance)
            for item, (identifier, legacy_id) in zip(
                tuition_items, tuition_ids, strict=True
            )
        ]

        place_entries = [
            (index, item)
            for index, item in enumerate(as_list(detail.get("places")))
            if isinstance(item, dict)
        ]
        place_items = [item for _index, item in place_entries]
        place_ids = deterministic_record_ids(
            "admission-place",
            place_items,
            key=lambda item: (
                first_text(item.get("id"), item.get("code"), item.get("title")),
            ),
            legacy_key=lambda item, index: (slug, item.get("title"), index),
            legacy_indices=[index for index, _item in place_entries],
        )
        places = [
            self._place(item, identifier, legacy_id, provenance)
            for item, (identifier, legacy_id) in zip(
                place_items, place_ids, strict=True
            )
        ]
        historical = [
            score
            for department in departments
            for score in department.historical_passing_scores
        ]
        programs = [
            program
            for department in departments
            for program in department.educational_programs
        ]
        courses = (
            detail.get("courses") if isinstance(detail.get("courses"), dict) else {}
        )

        return Major(
            id=stable_id("major", slug or summary.get("code") or summary.get("name")),
            status="ok" if detail else "error",
            detail_error=fetched.error,
            slug=slug,
            name=first_text(
                additional.get("name"), summary.get("name"), summary.get("title")
            ),
            code=first_text(additional.get("code"), summary.get("code")),
            qualification=first_text(
                additional.get("qualification"), summary.get("qualification")
            ),
            science_degree=clean_text(additional.get("scienceDegree")),
            study_period=clean_text(additional.get("studyPeriod")),
            military=bool_or_none(additional.get("military")),
            description=clean_text(detail.get("description")),
            faculties=faculties,
            faculty_id=faculty_id,
            faculty_name=faculty_name,
            tuition=tuition,
            entrance_requirements=current_requirements,
            places=places,
            historical_passing_scores=historical,
            key_disciplines=[
                clean_text(value)
                for value in as_list(courses.get("items"))
                if clean_text(value)
            ],
            departments=departments,
            educational_programs=programs,
            specializations=[
                clean_text(value)
                for value in as_list(detail.get("specializations"))
                if clean_text(value)
            ],
            provenance=provenance,
        )

    def _faculties(
        self, summary: dict[str, Any], provenance: SourceProvenance
    ) -> list[Faculty]:
        result: list[Faculty] = []
        for faculty in as_list(summary.get("faculties")):
            if not isinstance(faculty, dict):
                continue
            slug = first_text(
                faculty.get("slug"), faculty.get("code"), faculty.get("title")
            )
            result.append(
                Faculty(
                    id=stable_id("faculty", slug),
                    slug=str(faculty.get("slug", "")),
                    code=str(faculty.get("code", "")),
                    name=clean_text(faculty.get("title")),
                    provenance=provenance,
                )
            )
        return result

    def _summary_departments(
        self,
        summary: dict[str, Any],
        faculties: list[Faculty],
        provenance: SourceProvenance,
    ) -> list[Department]:
        by_slug = {faculty.slug: faculty for faculty in faculties}
        result: list[Department] = []
        for faculty_data in as_list(summary.get("faculties")):
            if not isinstance(faculty_data, dict):
                continue
            faculty_slug = str(faculty_data.get("slug", ""))
            faculty = by_slug.get(faculty_slug)
            for chair in as_list(faculty_data.get("chairs")):
                if not isinstance(chair, dict):
                    continue
                result.append(
                    Department(
                        id=stable_id(
                            "department", chair.get("slug"), chair.get("code")
                        ),
                        slug=str(chair.get("slug", "")),
                        code=str(chair.get("code", "")),
                        name=clean_text(chair.get("title")),
                        faculty_id=faculty.id
                        if faculty
                        else stable_id("faculty", faculty_slug),
                        faculty_name=faculty.name
                        if faculty
                        else clean_text(faculty_data.get("title")),
                        realized_programs=[],
                        short_description="",
                        description="",
                        practice_description="",
                        key_disciplines=[],
                        historical_passing_scores=[],
                        educational_programs=[],
                        phone="",
                        address="",
                        site="",
                        provenance=provenance,
                    )
                )
        return result

    def _departments(
        self,
        detail: dict[str, Any],
        major_slug: str,
        provenance: SourceProvenance,
    ) -> list[Department]:
        chairs = detail.get("chairs") if isinstance(detail.get("chairs"), dict) else {}
        result: list[Department] = []
        for chair in as_list(chairs.get("items")):
            if not isinstance(chair, dict):
                continue
            faculty_data = (
                chair.get("faculty") if isinstance(chair.get("faculty"), dict) else {}
            )
            faculty_slug = first_text(
                faculty_data.get("slug"), faculty_data.get("code")
            )
            faculty_id = stable_id("faculty", faculty_slug or faculty_data.get("title"))
            description = clean_text(chair.get("description"))
            courses = chair.get("courses")
            if isinstance(courses, dict):
                key_disciplines = [
                    clean_text(value)
                    for value in as_list(courses.get("items"))
                    if clean_text(value)
                ]
            else:
                key_disciplines = [
                    clean_text(value) for value in as_list(courses) if clean_text(value)
                ]
            department_id = stable_id(
                "department", chair.get("slug"), chair.get("code")
            )
            historical = self._historical_scores(
                chair, department_id, clean_text(chair.get("title")), provenance
            )
            programs_data = chair.get("educationalProgram")
            program_entries = [
                (index, item)
                for index, item in enumerate(
                    as_list(programs_data.get("items"))
                    if isinstance(programs_data, dict)
                    else []
                )
                if isinstance(item, dict)
            ]
            program_items = [item for _index, item in program_entries]
            program_ids = deterministic_record_ids(
                "educational-program",
                program_items,
                key=lambda item: (
                    major_slug,
                    department_id,
                    first_text(item.get("id"), item.get("code"), item.get("name")),
                ),
                legacy_key=lambda item, index: (
                    major_slug,
                    department_id,
                    item.get("code") or item.get("name"),
                    index,
                ),
                legacy_indices=[index for index, _item in program_entries],
            )
            programs = [
                self._program(
                    item,
                    major_slug,
                    department_id,
                    clean_text(chair.get("title")),
                    identifier,
                    legacy_id,
                    provenance,
                )
                for item, (identifier, legacy_id) in zip(
                    program_items, program_ids, strict=True
                )
            ]
            result.append(
                Department(
                    id=department_id,
                    slug=str(chair.get("slug", "")),
                    code=str(chair.get("code", "")),
                    name=clean_text(chair.get("title")),
                    faculty_id=faculty_id,
                    faculty_name=clean_text(faculty_data.get("title")),
                    realized_programs=[
                        line.strip(" ;")
                        for line in description.splitlines()
                        if line.strip(" ;")
                    ],
                    short_description=description,
                    description=clean_text(chair.get("about")),
                    practice_description=clean_text(chair.get("practice")),
                    key_disciplines=key_disciplines,
                    historical_passing_scores=historical,
                    educational_programs=programs,
                    phone=clean_text(chair.get("phone")),
                    address=clean_text(chair.get("address")),
                    site=normalize_url(chair.get("site")) if chair.get("site") else "",
                    provenance=provenance,
                )
            )
        return result

    def _program(
        self,
        item: dict[str, Any],
        major_slug: str,
        department_id: str,
        department_name: str,
        identifier: str,
        legacy_id: str,
        provenance: SourceProvenance,
    ) -> EducationalProgram:
        name = clean_text(item.get("name"))
        code = clean_text(item.get("code"))
        plan_url = (
            normalize_url(item.get("plan"), SITE_BASE) if item.get("plan") else ""
        )
        partners = [
            PracticePartner(
                id=stable_id(
                    "practice-partner",
                    identifier,
                    partner.get("url"),
                    partner.get("name"),
                ),
                name=clean_text(partner.get("name")),
                url=normalize_url(partner.get("url")) if partner.get("url") else "",
                image=normalize_url(partner.get("image"))
                if partner.get("image")
                else "",
                provenance=provenance,
            )
            for partner in as_list(item.get("practice"))
            if isinstance(partner, dict)
        ]
        return EducationalProgram(
            id=identifier,
            major_id=stable_id("major", major_slug),
            department_id=department_id,
            department_name=department_name,
            name=name,
            code=code,
            enrollment_available=bool_or_none(item.get("enrol")),
            location=clean_text(item.get("place")),
            description=clean_text(item.get("description")),
            disciplines=[
                clean_text(value)
                for value in as_list(item.get("discipline"))
                if clean_text(value)
            ],
            study_plan_url=plan_url,
            study_plan=StudyPlan(
                url=plan_url, status="not_resolved" if plan_url else "missing"
            ),
            practice_partners=partners,
            provenance=provenance,
            legacy_id=legacy_id,
        )

    def _historical_scores(
        self,
        chair: dict[str, Any],
        department_id: str,
        department_name: str,
        provenance: SourceProvenance,
    ) -> list[HistoricalPassingScore]:
        old_points = (
            chair.get("oldPoints") if isinstance(chair.get("oldPoints"), dict) else {}
        )
        point_entries = [
            (index, point)
            for index, point in enumerate(as_list(old_points.get("points")))
            if isinstance(point, dict)
        ]
        points = [point for _index, point in point_entries]
        identifiers = deterministic_record_ids(
            "historical-passing-score",
            points,
            key=lambda point: (department_id, point.get("year")),
            legacy_key=lambda point, index: (department_id, point.get("year"), index),
            legacy_indices=[index for index, _point in point_entries],
        )
        result: list[HistoricalPassingScore] = []
        for point, (identifier, legacy_id) in zip(points, identifiers, strict=True):
            parsed_year = parse_int(point.get("year"), "historical_passing_score.year")
            parsed_score = parse_int(
                point.get("count"), "historical_passing_score.score"
            )
            warnings = [
                warning
                for warning in (parsed_year.warning, parsed_score.warning)
                if warning
            ]
            result.append(
                HistoricalPassingScore(
                    id=identifier,
                    year=parsed_year.value
                    if isinstance(parsed_year.value, int)
                    else None,
                    score=parsed_score.value
                    if isinstance(parsed_score.value, int)
                    else None,
                    department_id=department_id,
                    department_name=department_name,
                    provenance=provenance,
                    legacy_id=legacy_id,
                    year_raw=parsed_year.raw,
                    score_raw=parsed_score.raw,
                    normalization_warnings=warnings,
                )
            )
        return result

    def _entrance_requirement(
        self,
        item: dict[str, Any],
        major_slug: str,
        identifier: str,
        legacy_id: str,
        provenance: SourceProvenance,
    ) -> EntranceRequirement:
        is_choice = bool_or_none(item.get("isChoice"))
        parsed_score = parse_int(
            item.get("point"), "entrance_requirement.minimum_score"
        )
        return EntranceRequirement(
            id=identifier,
            subject=clean_text(item.get("title")),
            minimum_score=parsed_score.value
            if isinstance(parsed_score.value, int)
            else None,
            is_choice=is_choice,
            requirement_type=(
                "по выбору"
                if is_choice is True
                else "обязательный"
                if is_choice is False
                else "не указано"
            ),
            provenance=provenance,
            legacy_id=legacy_id,
            minimum_score_raw=parsed_score.raw,
            normalization_warnings=[parsed_score.warning]
            if parsed_score.warning
            else [],
        )

    def _tuition(
        self,
        item: dict[str, Any],
        major_slug: str,
        identifier: str,
        legacy_id: str,
        provenance: SourceProvenance,
    ) -> TuitionOption:
        parsed_value = parse_decimal(item.get("value"), "tuition.value")
        parsed_discount = parse_decimal(
            item.get("discountValue"), "tuition.discount_value"
        )
        warnings = [
            warning
            for warning in (parsed_value.warning, parsed_discount.warning)
            if warning
        ]
        return TuitionOption(
            id=identifier,
            study_form=clean_text(item.get("studyForm")),
            value=parsed_value.value
            if isinstance(parsed_value.value, Decimal)
            else None,
            discount_value=parsed_discount.value
            if isinstance(parsed_discount.value, Decimal)
            else None,
            currency=clean_text(item.get("currency")),
            term=clean_text(item.get("term")),
            discount_url=normalize_url(item.get("urlDiscount"))
            if item.get("urlDiscount")
            else "",
            subtitle=clean_text(item.get("subtitle")),
            provenance=provenance,
            legacy_id=legacy_id,
            value_raw=parsed_value.raw,
            discount_value_raw=parsed_discount.raw,
            normalization_warnings=warnings,
        )

    @staticmethod
    def _place(
        item: dict[str, Any],
        identifier: str,
        legacy_id: str,
        provenance: SourceProvenance,
    ) -> AdmissionPlace:
        parsed_count = parse_int(item.get("count"), "admission_place.count")
        return AdmissionPlace(
            id=identifier,
            place_type=clean_text(item.get("title")),
            count=parsed_count.value if isinstance(parsed_count.value, int) else None,
            provenance=provenance,
            legacy_id=legacy_id,
            count_raw=parsed_count.raw,
            normalization_warnings=[parsed_count.warning]
            if parsed_count.warning
            else [],
        )

    @staticmethod
    def _faculty_id(
        detail_faculty: dict[str, Any], fallback: Faculty | None, major_slug: str
    ) -> str:
        slug = first_text(detail_faculty.get("slug"), detail_faculty.get("code"))
        if slug:
            return stable_id("faculty", slug)
        if fallback:
            return fallback.id
        return stable_id("faculty", major_slug, "unknown")
