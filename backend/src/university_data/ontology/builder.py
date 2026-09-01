from __future__ import annotations

from typing import Any

from ..domain.ids import global_stable_id


def build_ontology(
    university_id: str, records: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    type_names = {
        "universities": "university",
        "faculties": "faculty",
        "departments": "department",
        "study_directions": "study_direction",
        "programs": "program",
        "curricula": "curriculum",
        "teachers": "teacher",
        "admission_requirements": "admission_requirement",
        "tuition_options": "tuition_option",
        "disciplines": "discipline",
        "semesters": "semester",
        "semester_loads": "semester_load",
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
                merged_provenance = dict(previous) if isinstance(previous, dict) else {}
                incoming_provenance = incoming if isinstance(incoming, dict) else {}
                for key, value in incoming_provenance.items():
                    if key != "sources" and value not in (None, ""):
                        merged_provenance.setdefault(key, value)
                sources = (
                    list(merged_provenance.get("sources", []))
                    if isinstance(merged_provenance.get("sources"), list)
                    else []
                )
                for source in incoming_provenance.get("sources", []):
                    if source not in sources:
                        sources.append(source)
                if sources:
                    merged_provenance["sources"] = sources
                if merged_provenance:
                    properties["provenance"] = merged_provenance
            for field_name, target_type in (
                ("university_id", "university"),
                ("study_direction_id", "study_direction"),
                ("program_id", "program"),
                ("department_id", "department"),
                ("faculty_id", "faculty"),
                ("curriculum_id", "curriculum"),
                ("discipline_id", "discipline"),
                ("semester_id", "semester"),
            ):
                target = item.get(field_name)
                if field_name == "university_id" and target:
                    target = global_stable_id(university_id, "university", target)
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
    broken_links = [link for link in links if link["to"] not in known]
    links = [link for link in links if link["to"] in known]
    return {
        "schema_version": "1.0",
        "university_id": university_id,
        "objects": objects,
        "links": links,
        "broken_links": broken_links,
    }
