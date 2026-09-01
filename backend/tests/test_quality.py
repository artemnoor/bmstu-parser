import unittest
from pathlib import Path

from university_data.domain.ids import global_stable_id
from university_data.quality import build_quality_report
from university_data.universities.bmstu.adapter.study_plans.quality import (
    validate_extractions,
)


class QualityTests(unittest.TestCase):
    def test_quality_gate_reports_broken_link(self) -> None:
        university_id = global_stable_id("fake", "university", "fake")
        records = {
            "universities": [{"id": university_id, "university_id": "fake"}],
            "programs": [
                {
                    "id": "program-1",
                    "university_id": "fake",
                    "department_id": "missing",
                }
            ],
        }
        from university_data.ontology import build_ontology

        quality = build_quality_report(
            "fake",
            {"programs": True},
            records,
            ontology=build_ontology("fake", records),
        )
        self.assertFalse(quality["verification"]["passed"])
        self.assertEqual(quality["checks"]["orphan_links"], 1)

    def test_extraction_quality_rejects_declared_count_mismatch(self) -> None:
        reference = {
            "document_id": "doc-1",
            "local_path": "study_plans/a.pdf",
            "program_id": "program-1",
        }
        result = {
            "document": {
                "document_id": "doc-1",
                "kind": "pdf",
                "status": "ok",
                "table_count": 1,
                "row_count": 1,
                "cell_count": 1,
                "source_references": [reference],
                "expected_size": None,
                "source_size": 1,
                "expected_sha256": "",
                "source_sha256": "",
            },
            "layout_text": "Учебный план",
            "tables": [
                {
                    "id": "table-1",
                    "row_count": 2,
                    "rows": [[{"id": "cell-1"}]],
                }
            ],
        }
        quality = validate_extractions(
            [reference],
            [result],
            [Path("study_plans/a.pdf")],
            row_count=1,
            cell_count=1,
        )

        self.assertFalse(quality["verification"]["passed"])
        self.assertFalse(
            quality["verification"]["table_counts_match_materialized_data"]
        )
        self.assertEqual(quality["table_count_mismatches"][0]["declared"], 2)


if __name__ == "__main__":
    unittest.main()
