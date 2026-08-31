import unittest
from pathlib import Path

from bmstu_parser.ingestion.mirror_api import DetailFetch
from bmstu_parser.quality.checks import validate_dataset
from bmstu_parser.study_plans.quality import validate_extractions
from bmstu_parser.transform.normalize import Normalizer
from bmstu_parser.transform.ontology import OntologyBuilder


class QualityTests(unittest.TestCase):
    def test_quality_gate_reports_missing_detail(self) -> None:
        summary = {"slug": "broken", "name": "Broken", "code": "00.00.00"}
        detail = DetailFetch(summary, None, "timeout", "now")
        major = Normalizer().normalize(detail)
        ontology = OntologyBuilder().build([major])
        quality = validate_dataset([summary], {"count": 1}, [detail], [major], ontology)
        self.assertFalse(quality["verification"]["passed"])
        self.assertEqual(quality["detail_errors"][0]["slug"], "broken")

    def test_quality_gate_rejects_duplicate_detail_instead_of_matching_only_length(self) -> None:
        summaries = [
            {"slug": "first", "name": "First", "code": "01.00.00"},
            {"slug": "second", "name": "Second", "code": "02.00.00"},
        ]
        details = [
            DetailFetch(summaries[0], {}, None, "now"),
            DetailFetch(summaries[0], {}, None, "now"),
        ]
        majors = [Normalizer().normalize(item) for item in details]
        quality = validate_dataset(summaries, {"count": 2}, details, majors, {"objects": {}, "links": []})

        self.assertFalse(quality["verification"]["detail_for_every_list_item"])
        self.assertIn("second", quality["missing_detail_items"])
        self.assertIn("first", quality["duplicate_detail_items"])

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
        self.assertFalse(quality["verification"]["table_counts_match_materialized_data"])
        self.assertEqual(quality["table_count_mismatches"][0]["declared"], 2)


if __name__ == "__main__":
    unittest.main()
