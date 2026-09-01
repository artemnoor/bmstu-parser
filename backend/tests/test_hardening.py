from __future__ import annotations

import csv
import json
from pathlib import Path

from university_data.api.job_store import SqliteJobStore
from university_data.domain.ids import deterministic_record_ids
from university_data.universities.bmstu.adapter.domain.ids import (
    stable_id as legacy_stable_id,
)
from university_data.universities.bmstu.adapter.domain.provenance import (
    merge_provenance,
)
from university_data.universities.bmstu.adapter.ingestion.mirror_api import DetailFetch
from university_data.universities.bmstu.adapter.study_plans.semantics import (
    enrich_existing_dataset,
)
from university_data.universities.bmstu.adapter.transform.normalize import Normalizer


def _major(
    points: list[dict[str, object]], prices: list[dict[str, object]] | None = None
):
    summary = {
        "slug": "stable-major",
        "name": "Stable major",
        "code": "01.03.01",
        "faculties": [],
    }
    detail = {
        "additional": {"name": "Stable major", "code": "01.03.01"},
        "points": points,
        "price": prices or [],
        "chairs": {
            "items": [
                {
                    "slug": "stable-chair",
                    "title": "Stable chair",
                    "faculty": {},
                    "oldPoints": {"points": [{"year": "2025", "count": "250"}]},
                    "educationalProgram": {
                        "items": [{"code": "P-1", "name": "Stable program"}]
                    },
                }
            ]
        },
    }
    return Normalizer().normalize(DetailFetch(summary, detail, None, "now"))


def test_business_ids_survive_reordering_and_numeric_values_are_typed() -> None:
    first = _major(
        [
            {"title": "Математика", "point": "40", "isChoice": False},
            {"title": "Физика", "point": "39", "isChoice": True},
        ],
        [{"studyForm": "очная", "term": "2026", "value": "699 000"}],
    )
    second = _major(
        [
            {"title": "Физика", "point": "39", "isChoice": True},
            {"title": "Математика", "point": "40", "isChoice": False},
        ],
        [{"studyForm": "очная", "term": "2026", "value": "699 000"}],
    )

    assert {item.subject: item.id for item in first.entrance_requirements} == {
        item.subject: item.id for item in second.entrance_requirements
    }
    assert first.educational_programs[0].id == second.educational_programs[0].id
    assert first.tuition[0].value is not None
    assert str(first.tuition[0].value) == "699000"
    assert first.entrance_requirements[0].minimum_score == 40


def test_business_id_collisions_use_payload_variants_and_duplicate_ordinals() -> None:
    records = [
        {"code": "same", "name": "first"},
        {"code": "same", "name": "second"},
        {"code": "same", "name": "second"},
    ]
    identifiers = deterministic_record_ids(
        "example",
        "entity",
        records,
        key=lambda item: (item["code"],),
        legacy_key=lambda item, index: (item["code"], index),
    )
    assert len({identifier for identifier, _legacy in identifiers}) == 3
    assert identifiers[1][0] != identifiers[2][0]


def test_invalid_numeric_source_is_retained_as_raw_with_warning() -> None:
    major = _major([{"title": "Математика", "point": "неизвестно", "isChoice": False}])
    requirement = major.entrance_requirements[0]
    assert requirement.minimum_score is None
    assert requirement.minimum_score_raw == "неизвестно"
    assert requirement.normalization_warnings


def test_legacy_alias_keeps_original_source_array_position() -> None:
    major = _major([None, {"title": "Математика", "point": "40", "isChoice": False}])
    requirement = major.entrance_requirements[0]
    assert requirement.legacy_id == legacy_stable_id(
        "entrance-requirement", "stable-major", "Математика", 1
    )


def test_semantic_provenance_merge_keeps_non_domain_source_fields() -> None:
    merged = merge_provenance(
        {"source_url": "https://a.example", "raw_dataset": "a.jsonl"},
        {"source_url": "https://b.example", "raw_dataset": "b.jsonl"},
    )
    assert len(merged["sources"]) == 2
    assert {source["raw_dataset"] for source in merged["sources"]} == {
        "a.jsonl",
        "b.jsonl",
    }


def test_sqlite_store_recovers_interrupted_operation(tmp_path: Path) -> None:
    path = tmp_path / "operations.sqlite3"
    store = SqliteJobStore(path)
    store.create(
        {
            "id": "operation-1",
            "operation": "refresh",
            "status": "queued",
            "submitted_at_utc": "2026-01-01T00:00:00+00:00",
            "started_at_utc": None,
            "finished_at_utc": None,
            "result": None,
            "error": None,
        }
    )
    store.close()

    restarted = SqliteJobStore(path)
    record = restarted.get("operation-1")
    assert record is not None
    assert record["status"] == "failed"
    assert "перезапуском" in record["error"]
    restarted.close()


def test_semantic_facade_runs_full_curriculum_projection(tmp_path: Path) -> None:
    data_dir = tmp_path / "study_plan_data"
    data_dir.mkdir()
    table = {
        "id": "table-1",
        "document_id": "document-1",
        "page_number": 1,
        "section": "curriculum",
        "bbox": {"x0": 0, "x1": 100, "top": 0, "bottom": 100},
    }
    (data_dir / "study_plan_tables.jsonl").write_text(
        json.dumps(table, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    rows: list[dict[str, str]] = []

    def add(
        row_index: int, column_index: int, text: str, left: float, right: float
    ) -> None:
        rows.append(
            {
                "id": f"cell-{row_index}-{column_index}",
                "table_id": "table-1",
                "document_id": "document-1",
                "page_number": "1",
                "section": "curriculum",
                "row_index": str(row_index),
                "column_index": str(column_index),
                "text": text,
                "bbox": json.dumps({"x0": left, "x1": right, "top": 0, "bottom": 1}),
                "word_ids": "[]",
                "cell_kind": "native",
            }
        )

    for column, text, left, right in [
        (0, "Шифр", 0, 5),
        (1, "Наименование", 5, 10),
        (2, "Кафедра", 10, 15),
        (10, "1 - 17 недель", 50, 75),
        (11, "2 - 17 недель", 75, 100),
    ]:
        add(0, column, text, left, right)
    for column, text, left, right in [
        (3, "Общая, з.е.", 15, 20),
        (4, "Общая, час", 20, 25),
        (5, "Аудит. час", 25, 30),
        (6, "Лек", 30, 35),
        (7, "Сем", 35, 40),
        (8, "Лаб", 40, 45),
        (9, "Сам", 45, 50),
    ]:
        add(2, column, text, left, right)
    for column, text, left, right in [
        (0, "1", 0, 5),
        (1, "Алгебра", 5, 10),
        (2, "Кафедра", 10, 15),
        (3, "2", 15, 20),
        (4, "72", 20, 25),
        (5, "36", 25, 30),
        (6, "0", 30, 35),
        (7, "0", 35, 40),
        (8, "0", 40, 45),
        (9, "36", 45, 50),
        (10, "2", 50, 55),
        (11, "72", 55, 60),
        (12, "36", 60, 65),
        (13, "36", 65, 70),
        (14, "Экз", 70, 75),
    ]:
        add(4, column, text, left, right)

    with (data_dir / "study_plan_cells.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    report = enrich_existing_dataset(tmp_path)
    assert report["verification"]["passed"] is True
    assert report["counts"]["disciplines"] == 1
    assert (
        json.loads(
            (data_dir / "study_plan_disciplines.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )["name"]
        == "Алгебра"
    )
