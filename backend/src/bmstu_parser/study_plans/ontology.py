from __future__ import annotations

from typing import Any

from ..domain.ids import link_id, stable_id


class StudyPlanOntologyBuilder:
    """Expose extracted plan datasets as auditable document/table/row objects."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, dict[str, Any]]] = {}
        self.links: dict[str, dict[str, Any]] = {}

    def add_object(
        self,
        object_type: str,
        identifier: str,
        properties: dict[str, Any],
        provenance: dict[str, Any],
    ) -> str:
        bucket = self.objects.setdefault(object_type, {})
        bucket.setdefault(
            identifier,
            {
                "id": identifier,
                "object_type": object_type,
                "properties": properties,
                "provenance": provenance,
            },
        )
        return identifier

    def add_link(
        self, link_type: str, from_id: str, to_id: str, provenance: dict[str, Any]
    ) -> str:
        identifier = link_id(link_type, from_id, to_id)
        self.links.setdefault(
            identifier,
            {
                "id": identifier,
                "link_type": link_type,
                "from_id": from_id,
                "to_id": to_id,
                "properties": {},
                "provenance": provenance,
            },
        )
        return identifier

    def build(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        for result in results:
            document = result["document"]
            document_id = document["document_id"]
            provenance = {
                "source_url": document.get("source_url", ""),
                "resolved_url": document.get("resolved_url", ""),
                "local_path": document.get("local_path", ""),
                "raw_dataset": "study_plan_tables.jsonl",
                "extracted_at_utc": document.get("extracted_at_utc", ""),
            }
            document_object = self.add_object(
                "study_plan_document",
                document_id,
                {
                    "source_key": document_id,
                    "local_path": document.get("local_path", ""),
                    "kind": document.get("kind", ""),
                    "status": document.get("status", ""),
                    "source_size": document.get("source_size"),
                    "source_sha256": document.get("source_sha256", ""),
                    "page_count": document.get("page_count", 0),
                    "table_count": document.get("table_count", 0),
                    "row_count": document.get("row_count", 0),
                    "cell_count": document.get("cell_count", 0),
                    "raw_layout_path": document.get("raw_layout_path", ""),
                },
                provenance,
            )
            references = document.get("source_references", [])
            for reference in references:
                program_id = reference.get("program_id") or stable_id(
                    "educational-program", reference.get("program_name")
                )
                self.add_object(
                    "educational_program",
                    program_id,
                    {
                        "source_key": program_id,
                        "major_id": reference.get("major_id", ""),
                        "major_code": reference.get("major_code", ""),
                        "major_name": reference.get("major_name", ""),
                        "program_code": reference.get("program_code", ""),
                        "program_name": reference.get("program_name", ""),
                    },
                    provenance,
                )
                self.add_link(
                    "study_plan_document_for_program",
                    document_object,
                    program_id,
                    provenance,
                )
            for table in result.get("tables", []):
                table_object = self.add_object(
                    "study_plan_table",
                    table["id"],
                    {
                        "source_key": table["id"],
                        "page_number": table.get("page_number"),
                        "table_index": table.get("table_index"),
                        "section": table.get("section", ""),
                        "bbox": table.get("bbox"),
                        "row_count": table.get("row_count", 0),
                        "column_count": table.get("column_count", 0),
                        "extraction_method": table.get("extraction_method", ""),
                    },
                    provenance,
                )
                self.add_link(
                    "study_plan_document_contains_table",
                    document_object,
                    table_object,
                    provenance,
                )
                for row_index, cells in enumerate(table.get("rows", [])):
                    values = [cell.get("text", "") for cell in cells]
                    row_identifier = stable_id("study-plan-row", table["id"], row_index)
                    row_object = self.add_object(
                        "study_plan_row",
                        row_identifier,
                        {
                            "source_key": row_identifier,
                            "table_id": table["id"],
                            "page_number": table.get("page_number"),
                            "row_index": row_index,
                            "first_cell": values[0] if values else "",
                            "second_cell": values[1] if len(values) > 1 else "",
                            "cell_count": len(cells),
                            "cells_dataset": "study_plan_cells.csv",
                            "cells_locator": {
                                "table_id": table["id"],
                                "row_index": row_index,
                            },
                        },
                        provenance,
                    )
                    self.add_link(
                        "study_plan_table_contains_row",
                        table_object,
                        row_object,
                        provenance,
                    )
        return {
            "objects": {
                object_type: [bucket[key] for key in sorted(bucket)]
                for object_type, bucket in sorted(self.objects.items())
            },
            "links": [self.links[key] for key in sorted(self.links)],
        }
