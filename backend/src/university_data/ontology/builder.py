from __future__ import annotations

from typing import Any


def build_ontology(
    university_id: str, records: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    type_names = {
        "faculties": "faculty",
        "departments": "department",
        "study_directions": "study_direction",
        "programs": "program",
        "curricula": "curriculum",
        "teachers": "teacher",
        "admission_requirements": "admission_requirement",
        "tuition_options": "tuition_option",
        "disciplines": "discipline",
    }
    objects_by_id: dict[str, dict[str, Any]] = {}
    links: list[dict[str, Any]] = []
    for entity_type, items in records.items():
        object_type = type_names.get(entity_type, entity_type)
        for item in items:
            identifier = item.get("id")
            if not identifier:
                continue
            current = objects_by_id.get(identifier)
            if current is None:
                objects_by_id[identifier] = {
                    "id": identifier,
                    "type": object_type,
                    "properties": item,
                }
            else:
                properties = current["properties"]
                for key, value in item.items():
                    if key != "provenance" and value not in (None, "", [], {}):
                        properties[key] = value
                previous = properties.get("provenance", {})
                incoming = item.get("provenance", {})
                sources = (
                    list(previous.get("sources", []))
                    if isinstance(previous, dict)
                    else []
                )
                for source in (
                    incoming.get("sources", []) if isinstance(incoming, dict) else []
                ):
                    if source not in sources:
                        sources.append(source)
                if sources:
                    properties["provenance"] = {"sources": sources}
            for field_name, target_type in (
                ("university_id", "university"),
                ("study_direction_id", "study_direction"),
                ("program_id", "program"),
                ("department_id", "department"),
                ("faculty_id", "faculty"),
                ("discipline_id", "discipline"),
                ("semester_id", "semester"),
            ):
                target = item.get(field_name)
                if target:
                    links.append(
                        {
                            "id": f"{identifier}:{field_name}:{target}",
                            "type": field_name,
                            "from": identifier,
                            "to": target,
                            "target_type": target_type,
                        }
                    )
    objects = list(objects_by_id.values())
    known = {item["id"] for item in objects}
    links = [
        link
        for link in links
        if link["to"] in known or link["target_type"] == "university"
    ]
    return {
        "schema_version": "1.0",
        "university_id": university_id,
        "objects": objects,
        "links": links,
    }
