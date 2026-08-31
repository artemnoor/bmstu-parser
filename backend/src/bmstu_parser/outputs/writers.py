from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

from ..config import API_BASE, DEGREE, LIST_ENDPOINT, SOURCE_PAGE
from ..domain.models import Major
from ..ingestion.mirror_api import DetailFetch
from ..runtime.atomic import atomic_text_writer, atomic_write_json
from .projections import (
    canonical_records,
    department_rows,
    discipline_rows,
    educational_program_rows,
    entrance_subject_rows,
    historical_score_rows,
    major_rows,
    study_plan_file_rows,
    tuition_rows,
)


def write_json(path: Path, value: Any) -> None:
    atomic_write_json(path, value)


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    with atomic_text_writer(path, encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: "" if row.get(field) is None else row.get(field, "") for field in fieldnames})


def write_raw_snapshots(
    output_dir: Path,
    summaries: list[dict[str, Any]],
    list_meta: dict[str, Any],
    details: list[DetailFetch],
) -> None:
    raw_dir = output_dir / "raw"
    raw_details = raw_dir / "details"
    raw_details.mkdir(parents=True, exist_ok=True)
    write_json(raw_dir / "majors_list.json", {"meta": list_meta, "data": summaries})
    errors: list[dict[str, Any]] = []
    for item in details:
        slug = str(item.summary.get("slug", "unknown"))
        write_json(
            raw_details / f"{slug}.json",
            {
                "summary": item.summary,
                "detail": item.detail,
                "error": item.error,
                "fetched_at_utc": item.fetched_at_utc,
            },
        )
        if item.error:
            errors.append({"slug": slug, "error": item.error})
    write_json(raw_dir / "detail_errors.json", errors)


def write_dataset(
    output_dir: Path,
    majors: list[Major],
    ontology: dict[str, Any],
    quality: dict[str, Any],
    summaries: list[dict[str, Any]],
    list_meta: dict[str, Any],
    details: list[DetailFetch],
    fetched_at_utc: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_raw_snapshots(output_dir, summaries, list_meta, details)

    source = {
        "page": SOURCE_PAGE,
        "api_base": API_BASE,
        "list_endpoint": LIST_ENDPOINT,
        "degree": DEGREE,
        "fetched_at_utc": fetched_at_utc,
        "raw_dataset": "raw/majors_list.json",
    }
    write_json(
        output_dir / "bmstu_bachelor_majors.json",
        {
            "schema_version": "2.0",
            "source": source,
            "quality": quality,
            "records": canonical_records(majors),
            "ontology": ontology,
        },
    )
    write_json(
        output_dir / "ontology.json",
        {"schema_version": "2.0", "source": source, **ontology},
    )
    write_json(output_dir / "parse_report.json", {"schema_version": "2.0", "source": source, **quality})

    projections: list[tuple[str, list[dict[str, Any]]]] = [
        ("majors.csv", major_rows(majors)),
        ("departments.csv", department_rows(majors)),
        ("educational_programs.csv", educational_program_rows(majors)),
        ("entrance_subjects.csv", entrance_subject_rows(majors)),
        ("tuition.csv", tuition_rows(majors)),
        ("disciplines.csv", discipline_rows(majors)),
        ("historical_passing_scores.csv", historical_score_rows(majors)),
        ("study_plan_files.csv", study_plan_file_rows(majors)),
    ]
    for filename, rows in projections:
        fields = sorted({key for row in rows for key in row})
        write_csv(output_dir / filename, rows, fields)
