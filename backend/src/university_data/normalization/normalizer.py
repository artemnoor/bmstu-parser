from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..core.source_models import SourceProgram, SourceTeacher
from ..domain.ids import global_stable_id
from ..domain.provenance import FieldMeta


def _meta(
    status: str, method: str, confidence: float, source: Any
) -> dict[str, FieldMeta]:
    return {
        field: FieldMeta(status, method, confidence, sources=[source] if source else [])
        for field in ("name", "code")
    }


class CanonicalNormalizer:
    """Convert typed source DTOs into flat canonical records plus metadata."""

    def program(self, university_id: str, source: SourceProgram) -> dict[str, Any]:
        identifier = global_stable_id(
            university_id, "program", source.source_key or source.code or source.name
        )
        direction_id = global_stable_id(
            university_id, "study_direction", source.study_direction_key or source.code
        )
        return {
            "id": identifier,
            "university_id": university_id,
            "study_direction_id": direction_id,
            "name": source.name,
            "code": source.code,
            "department_id": global_stable_id(
                university_id, "department", source.department_key
            )
            if source.department_key
            else "",
            "description": source.description,
            "study_plan_url": source.study_plan_url,
            "field_meta": {
                "name": FieldMeta("published", "source", 1.0).to_dict(),
                "code": FieldMeta(
                    "published" if source.code else "not_published",
                    "source",
                    1.0 if source.code else 0.0,
                ).to_dict(),
            },
            "extensions": {},
            "provenance": source.provenance.to_dict(),
        }

    def teacher(self, university_id: str, source: SourceTeacher) -> dict[str, Any]:
        identifier = global_stable_id(
            university_id, "teacher", source.source_key or source.name
        )
        return {
            "id": identifier,
            "university_id": university_id,
            "name": source.name,
            "position": source.position,
            "department_id": global_stable_id(
                university_id, "department", source.department_key
            )
            if source.department_key
            else "",
            "email": source.email,
            "field_meta": {
                "name": FieldMeta("published", "source", 1.0).to_dict(),
            },
            "extensions": {},
            "provenance": source.provenance.to_dict(),
        }

    @staticmethod
    def source_dict(source: Any) -> dict[str, Any]:
        return (
            asdict(source) if hasattr(source, "__dataclass_fields__") else dict(source)
        )
