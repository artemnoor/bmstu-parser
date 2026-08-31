from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..domain.ids import link_id
from ..domain.provenance import merge_provenance, provenance_dict
from ..outputs.writers import write_json
from .semantic_shared import read_jsonl


def _merge_properties(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list) and isinstance(merged.get(key), list):
            values = list(merged[key])
            for item in value:
                if item not in values:
                    values.append(item)
            merged[key] = values
        elif key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = value
    return merged


def extend_ontology_with_semantics(
    data_dir: Path, semantic: dict[str, Any]
) -> dict[str, Any]:
    ontology_path = data_dir / "study_plan_ontology.json"
    ontology = (
        json.loads(ontology_path.read_text(encoding="utf-8"))
        if ontology_path.exists()
        else {"schema_version": "2.0", "objects": {}, "links": []}
    )
    object_buckets: dict[str, dict[str, dict[str, Any]]] = {
        object_type: {item["id"]: item for item in values}
        for object_type, values in ontology.get("objects", {}).items()
    }
    links = {item["id"]: item for item in ontology.get("links", [])}
    documents = {
        item["document_id"]: item
        for item in read_jsonl(data_dir / "study_plan_documents.jsonl")
    }
    row_object_ids = {
        item["id"] for item in object_buckets.get("study_plan_row", {}).values()
    }

    def provenance(document_id: str, dataset: str) -> dict[str, Any]:
        document = documents.get(document_id, {})
        return {
            "source_url": document.get("source_url", ""),
            "resolved_url": document.get("resolved_url", ""),
            "local_path": document.get("local_path", ""),
            "raw_dataset": dataset,
            "extracted_at_utc": document.get("extracted_at_utc", ""),
        }

    def add_object(
        object_type: str,
        identifier: str,
        properties: dict[str, Any],
        source: dict[str, Any],
    ) -> None:
        bucket = object_buckets.setdefault(object_type, {})
        candidate = {
            "id": identifier,
            "object_type": object_type,
            "properties": properties,
            "provenance": provenance_dict(source),
        }
        existing = bucket.get(identifier)
        if existing is None:
            bucket[identifier] = candidate
        else:
            existing["properties"] = _merge_properties(
                existing.get("properties", {}), properties
            )
            existing["provenance"] = merge_provenance(
                existing.get("provenance", {}), source
            )

    def add_link(
        link_type: str, from_id: str, to_id: str, source: dict[str, Any]
    ) -> None:
        identifier = link_id(link_type, from_id, to_id)
        candidate = {
            "id": identifier,
            "link_type": link_type,
            "from_id": from_id,
            "to_id": to_id,
            "properties": {},
            "provenance": provenance_dict(source),
        }
        existing = links.get(identifier)
        if existing is None:
            links[identifier] = candidate
        else:
            existing["provenance"] = merge_provenance(
                existing.get("provenance", {}), source
            )

    for discipline in semantic["disciplines"]:
        source = provenance(discipline["document_id"], "study_plan_disciplines.jsonl")
        add_object(
            "study_plan_discipline",
            discipline["id"],
            {
                "source_key": discipline["id"],
                "code": discipline["code"],
                "name": discipline["name"],
                "department": discipline["department"],
                "part_type": discipline["part_type"],
                "section_path": discipline["section_path"],
                "workload": discipline["workload"],
                "class_hours": discipline["class_hours"],
                "semester_count": discipline["semester_count"],
                "source_row_id": discipline["source_row_id"],
                "source_cells_dataset": discipline["source_cells_dataset"],
            },
            source,
        )
        document_id = discipline["document_id"]
        if document_id in object_buckets.get("study_plan_document", {}):
            add_link(
                "study_plan_document_has_discipline",
                document_id,
                discipline["id"],
                source,
            )
        if discipline["source_row_id"] in row_object_ids:
            add_link(
                "study_plan_row_is_discipline",
                discipline["source_row_id"],
                discipline["id"],
                source,
            )

    for load in semantic["semester_loads"]:
        source = provenance(load["document_id"], "study_plan_semester_load.csv")
        add_object(
            "study_plan_semester_load",
            load["id"],
            {
                "source_key": load["id"],
                "discipline_id": load["discipline_id"],
                "semester": load["semester"],
                "weeks": load["weeks"],
                "active": load["active"],
                "has_numeric_load": load["has_numeric_load"],
                "credits": load["credits"],
                "hours": load["hours"],
                "audited_hours": load["audited_hours"],
                "independent_or_other_hours": load["independent_or_other_hours"],
                "control": load["control"],
                "control_tokens": load["control_tokens"],
                "control_kinds": load["control_kinds"],
                "raw_bands": load["raw_bands"],
                "normalization_notes": load["normalization_notes"],
                "source_row_id": load["source_row_id"],
                "source_cells_dataset": "study_plan_cells.csv",
            },
            source,
        )
        add_link(
            "study_plan_discipline_has_semester_load",
            load["discipline_id"],
            load["id"],
            source,
        )

    for entity in semantic.get("resolution", {}).get("entities", []):
        source_discipline_ids = entity.get("source_discipline_ids", [])
        source_document_id = next(
            (
                discipline.get("document_id", "")
                for discipline in semantic["disciplines"]
                if discipline.get("id")
                == (source_discipline_ids[0] if source_discipline_ids else "")
            ),
            "",
        )
        source = provenance(source_document_id, "study_plan_discipline_entities.jsonl")
        add_object(
            "study_plan_discipline_entity",
            entity["id"],
            {
                "source_key": entity["id"],
                "resolution_key": entity["resolution_key"],
                "status": entity["status"],
                "code": entity["code"],
                "name": entity["name"],
                "aliases": entity["aliases"],
                "source_discipline_ids": source_discipline_ids,
                "source_documents": entity["source_documents"],
                "conflicts": entity["conflicts"],
            },
            source,
        )
        for source_discipline_id in source_discipline_ids:
            if source_discipline_id in object_buckets.get("study_plan_discipline", {}):
                add_link(
                    "study_plan_discipline_resolves_to_entity",
                    source_discipline_id,
                    entity["id"],
                    source,
                )

    ontology["schema_version"] = "3.1"
    ontology["objects"] = {
        object_type: [bucket[key] for key in sorted(bucket)]
        for object_type, bucket in sorted(object_buckets.items())
    }
    ontology["links"] = [links[key] for key in sorted(links)]
    write_json(ontology_path, ontology)
    return ontology
