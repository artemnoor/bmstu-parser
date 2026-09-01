from __future__ import annotations

import csv
import json
from pathlib import Path

from university_data.runtime.atomic import atomic_text_writer, atomic_write_json
from university_data.runtime.checkpoints import CheckpointStore, file_fingerprint
from university_data.universities.bmstu.adapter.study_plans.pipeline import (
    StudyPlanExtractionPipeline,
)
from university_data.universities.bmstu.adapter.study_plans.readers import (
    DoclingDocumentReader,
)
from university_data.universities.bmstu.adapter.study_plans.resolution import (
    resolve_disciplines,
)
from university_data.universities.bmstu.adapter.study_plans.rules import (
    validate_curriculum_contract,
)


def test_atomic_writer_preserves_previous_artifact_on_failure(tmp_path: Path) -> None:
    destination = tmp_path / "dataset.jsonl"
    destination.write_text("old\n", encoding="utf-8")

    try:
        with atomic_text_writer(destination) as stream:
            stream.write("new\n")
            raise RuntimeError("simulated writer failure")
    except RuntimeError:
        pass

    assert destination.read_text(encoding="utf-8") == "old\n"
    assert list(tmp_path.glob("*.tmp")) == []


def test_checkpoint_store_hits_only_matching_fingerprint(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-test")
    result_path = tmp_path / "result.json"
    atomic_write_json(result_path, {"document": {"status": "ok"}})
    store = CheckpointStore(tmp_path / "checkpoints")
    fingerprint = file_fingerprint(source, "v1", "native")

    store.mark("doc-1", fingerprint, result_path, status="ok")

    assert store.get("doc-1", fingerprint) is not None
    assert store.get("doc-1", file_fingerprint(source, "v2", "native")) is None


def test_curriculum_contract_reports_orphan_loads_and_missing_sources() -> None:
    report = validate_curriculum_contract(
        rows=[{"id": "row-1", "source_cell_ids": ["cell-1"]}],
        disciplines=[{"id": "discipline-1", "code": "1", "name": "Алгебра"}],
        semester_loads=[{"id": "load-1", "discipline_id": "missing-discipline"}],
    )

    assert report["verification"]["discipline_code_and_name_present"]
    assert not report["verification"]["semester_loads_reference_disciplines"]
    assert not report["verification"]["passed"]
    assert report["violations"] == [
        {"rule": "load_references_discipline", "id": "load-1"}
    ]


def test_resolver_is_non_destructive_and_keeps_ambiguous_collisions_visible() -> None:
    disciplines = [
        {
            "id": "d-1",
            "document_id": "doc-1",
            "code": "101",
            "name": "Алгебра",
            "department": "Кафедра 1",
        },
        {
            "id": "d-2",
            "document_id": "doc-2",
            "code": "101",
            "name": "Алгебра",
            "department": "Кафедра 2",
        },
        {
            "id": "d-3",
            "document_id": "doc-3",
            "code": "202",
            "name": "Физика",
            "department": "Кафедра 3",
        },
        {
            "id": "d-4",
            "document_id": "doc-4",
            "code": "202",
            "name": "Механика",
            "department": "Кафедра 4",
        },
    ]
    original = json.loads(json.dumps(disciplines, ensure_ascii=False))

    resolution = resolve_disciplines(disciplines)

    assert disciplines == original
    assert resolution["counts"] == {
        "source_disciplines": 4,
        "entities": 3,
        "aliases": 4,
        "ambiguous_entities": 0,
        "code_collision_candidates": 1,
    }
    assert resolution["verification"]["passed"]
    assert resolution["verification"]["no_ambiguous_entities"]
    assert resolution["verification"]["code_collision_candidates_are_diagnostic"]
    assert resolution["code_collision_candidates"][0]["code"] == "202"


def test_docling_adapter_maps_structured_tables_to_canonical_cells(
    tmp_path: Path,
) -> None:
    class FakeDocument:
        def export_to_dict(self) -> dict[str, object]:
            return {
                "pages": {"1": {"size": {"width": 1000, "height": 700}}},
                "texts": [{"text": "Учебный план"}],
                "tables": [
                    {
                        "prov": [
                            {
                                "page_no": 1,
                                "bbox": {"l": 10, "t": 20, "r": 900, "b": 300},
                            }
                        ],
                        "data": {
                            "grid": [
                                [
                                    {"text": "Шифр", "column_header": True},
                                    {"text": "Наименование"},
                                ]
                            ]
                        },
                    }
                ],
            }

        def export_to_markdown(self) -> str:
            return "# Учебный план"

    class FakeResult:
        document = FakeDocument()

    class FakeConverter:
        def convert(self, path: Path) -> FakeResult:
            assert path.name == "plan.pdf"
            return FakeResult()

    reader = DoclingDocumentReader(converter_factory=lambda: FakeConverter())
    pages, tables, markdown, warnings = reader.extract(tmp_path / "plan.pdf", "doc-1")

    assert markdown == "# Учебный план"
    assert pages[0]["table_ids"] == [tables[0]["id"]]
    assert tables[0]["section"] == "time_budget_summary"
    assert tables[0]["rows"][0][0]["text"] == "Шифр"
    assert tables[0]["rows"][0][0]["cell_kind"] == "docling_header_cell"
    assert any("word-level anchors" in warning for warning in warnings)


def test_extraction_pipeline_resumes_from_checkpoint_with_custom_reader(
    tmp_path: Path,
) -> None:
    (tmp_path / "study_plans").mkdir()
    (tmp_path / "study_plans" / "plan.pdf").write_bytes(b"%PDF-fake")
    with (tmp_path / "study_plan_files.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "local_path", "program_id"])
        writer.writeheader()
        writer.writerow(
            {
                "id": "doc-1",
                "local_path": "study_plans/plan.pdf",
                "program_id": "program-1",
            }
        )

    class FakeReader:
        name = "test-reader"

        def __init__(self) -> None:
            self.calls = 0

        def extract(
            self, path: Path, document_id: str
        ) -> tuple[list[dict], list[dict], str, list[str]]:
            self.calls += 1
            table_id = f"table-{document_id}"
            cell = {
                "id": "cell-1",
                "table_id": table_id,
                "row_index": 0,
                "column_index": 0,
                "text": "Алгебра",
                "bbox": None,
                "word_ids": [],
                "cell_kind": "test",
            }
            table = {
                "id": table_id,
                "document_id": document_id,
                "page_number": 1,
                "table_index": 0,
                "section": "other",
                "bbox": None,
                "row_count": 1,
                "column_count": 1,
                "rows": [[cell]],
                "extraction_method": "test-reader",
            }
            page = {
                "page_number": 1,
                "width": None,
                "height": None,
                "words": [],
                "lines": [],
                "table_ids": [table_id],
            }
            return [page], [table], "raw text", []

    reader = FakeReader()
    first_quality = StudyPlanExtractionPipeline(tmp_path, reader_backend=reader).run()
    second_quality = StudyPlanExtractionPipeline(tmp_path, reader_backend=reader).run()

    assert first_quality["verification"]["passed"]
    assert second_quality["verification"]["passed"]
    assert reader.calls == 1
    assert (
        tmp_path / "study_plan_data" / "checkpoints" / "study_plan_checkpoints.json"
    ).exists()
    assert (
        json.loads(
            (tmp_path / "study_plan_data" / "study_plan_documents.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )["extraction_backend"]
        == "test-reader"
    )
