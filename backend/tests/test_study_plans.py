import unittest
from pathlib import Path

from bmstu_parser.study_plans.quality import validate_extractions
from bmstu_parser.study_plans.reader import curriculum_row_record
from bmstu_parser.study_plans.semantics import _semantic_row


class StudyPlanTests(unittest.TestCase):
    def test_curriculum_row_keeps_all_cell_values(self) -> None:
        table = {
            "id": "table-1",
            "document_id": "document-1",
            "page_number": 2,
            "section": "curriculum",
        }
        cells = [
            {"id": "cell-1", "text": "1"},
            {"id": "cell-2", "text": "Иностранный язык"},
            {"id": "cell-3", "text": "Л3"},
            {"id": "cell-4", "text": "12"},
        ]
        row = curriculum_row_record(table, 5, cells)
        self.assertEqual(row["row_role"], "discipline")
        self.assertEqual(row["code"], "1")
        self.assertEqual(
            [cell["text"] for cell in row["cells"]],
            ["1", "Иностранный язык", "Л3", "12"],
        )

    def test_quality_gate_checks_all_references_for_deduplicated_document(self) -> None:
        canonical = {
            "document_id": "doc-1",
            "local_path": "study_plans/a.pdf",
            "program_id": "program-1",
        }
        secondary = {
            "document_id": "doc-1",
            "local_path": "study_plans/a.pdf",
            "program_id": "program-2",
        }
        result = {
            "document": {
                "document_id": "doc-1",
                "kind": "pdf",
                "status": "ok",
                "table_count": 1,
                "source_references": [canonical, secondary],
                "expected_size": None,
                "source_size": 1,
                "expected_sha256": "",
                "source_sha256": "",
            },
            "layout_text": "Учебный план",
        }
        quality = validate_extractions(
            [canonical],
            [result],
            [Path("study_plans/a.pdf")],
            row_count=1,
            cell_count=1,
            all_references=[canonical, secondary],
        )
        self.assertTrue(
            quality["verification"]["canonical_document_count_matches_manifest"]
        )
        self.assertTrue(quality["verification"]["all_manifest_references_attached"])
        self.assertEqual(quality["counts"]["manifest_references"], 2)

    def test_semantics_extracts_subject_load_and_control(self) -> None:
        table = {
            "id": "table-semantic",
            "document_id": "document-semantic",
            "page_number": 1,
            "bbox": {"x0": 0, "x1": 20, "top": 0, "bottom": 10},
        }
        schema = {
            "base_spans": {
                "code": [0.00, 0.05],
                "name": [0.05, 0.10],
                "department": [0.10, 0.15],
                "total_credits": [0.15, 0.20],
                "total_hours": [0.20, 0.25],
                "audited_hours": [0.25, 0.30],
                "lecture_hours": [0.30, 0.35],
                "seminar_hours": [0.35, 0.40],
                "lab_hours": [0.40, 0.45],
                "independent_or_other_hours": [0.45, 0.50],
            },
            "semester_start_rel": 0.50,
            "semester_end_rel": 1.0,
            "semester_count": 2,
            "semester_headers": {1: {"weeks": 17}, 2: {"weeks": 17}},
        }
        values = [
            "1",
            "Математика",
            "МТ",
            "4",
            "144",
            "68",
            "34",
            "34",
            "0",
            "76",
            "4",
            "144",
            "68",
            "76",
            "Экз",
        ]
        cells = []
        words = {}
        for index, value in enumerate(values):
            left = index
            right = index + 1
            word_id = f"word-{index}"
            cells.append(
                {
                    "id": f"cell-{index}",
                    "column_index": index,
                    "row_index": 4,
                    "text": value,
                    "bbox": {"x0": left, "x1": right, "top": 1, "bottom": 2},
                    "word_ids": [word_id],
                }
            )
            words[word_id] = {
                "id": word_id,
                "text": value,
                "x0": left + 0.5,
                "x1": right - 0.5,
                "top": 1,
                "bottom": 2,
            }
        row, discipline, loads = _semantic_row(
            table,
            4,
            cells,
            schema,
            words,
            {"section_path": [], "part_type": "mandatory"},
        )
        self.assertEqual(row["row_kind"], "discipline")
        self.assertIsNotNone(discipline)
        self.assertEqual(discipline["name"], "Математика")
        self.assertEqual(discipline["workload"]["hours"], 144)
        self.assertEqual(loads[0]["credits"], 4)
        self.assertEqual(loads[0]["hours"], 144)
        self.assertEqual(loads[0]["control_kinds"], ["exam"])

    def test_semantics_assigns_merged_control_by_word_start(self) -> None:
        table = {
            "id": "table-merged-control",
            "document_id": "document-merged-control",
            "page_number": 1,
            "bbox": {"x0": 0, "x1": 100, "top": 0, "bottom": 10},
        }
        schema = {
            "base_spans": {
                "code": [0.00, 0.05],
                "name": [0.05, 0.10],
                "department": [0.10, 0.15],
                "total_credits": [0.15, 0.20],
                "total_hours": [0.20, 0.25],
                "audited_hours": [0.25, 0.30],
                "lecture_hours": [0.30, 0.35],
                "seminar_hours": [0.35, 0.40],
                "lab_hours": [0.40, 0.45],
                "independent_or_other_hours": [0.45, 0.50],
            },
            "semester_start_rel": 0.50,
            "semester_end_rel": 1.0,
            "semester_count": 4,
            "semester_headers": {number: {"weeks": 17} for number in range(1, 5)},
        }
        values = ["1", "Математика", "МТ", "4", "144", "68", "34", "34", "0", "76"]
        cells = []
        words = {}
        for index, value in enumerate(values):
            left = index * 5
            right = left + 5
            word_id = f"base-word-{index}"
            cells.append(
                {
                    "id": f"base-cell-{index}",
                    "column_index": index,
                    "row_index": 4,
                    "text": value,
                    "bbox": {"x0": left, "x1": right, "top": 1, "bottom": 2},
                    "word_ids": [word_id],
                }
            )
            words[word_id] = {
                "id": word_id,
                "text": value,
                "x0": left + 1,
                "x1": right - 1,
                "top": 1,
                "bottom": 2,
            }

        cells.append(
            {
                "id": "merged-control-cell",
                "column_index": 10,
                "row_index": 4,
                "text": "Зчт",
                "bbox": {"x0": 85, "x1": 95, "top": 1, "bottom": 2},
                "word_ids": ["merged-control-word"],
            }
        )
        words["merged-control-word"] = {
            "id": "merged-control-word",
            "text": "Зчт",
            "x0": 85,
            "x1": 95,
            "top": 1,
            "bottom": 2,
        }

        _row, _discipline, loads = _semantic_row(
            table,
            4,
            cells,
            schema,
            words,
            {"section_path": [], "part_type": "mandatory"},
        )

        self.assertEqual(loads[2]["control_tokens"], ["Зчт"])
        self.assertEqual(loads[2]["control_kinds"], ["credit"])
        self.assertIsNone(loads[3]["credits"])
        self.assertEqual(loads[3]["control_tokens"], [])
        self.assertIn(
            "control_token_removed_from_credits", loads[3]["normalization_notes"]
        )


if __name__ == "__main__":
    unittest.main()
