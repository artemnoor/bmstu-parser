from __future__ import annotations

import csv
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


class DatasetNotFoundError(LookupError):
    pass


class DatasetUnavailableError(FileNotFoundError):
    pass


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    name: str
    relative_path: Path
    format: str
    description: str


DATASET_SPECS: tuple[DatasetSpec, ...] = (
    DatasetSpec("majors", Path("majors.csv"), "csv", "Направления подготовки и их свойства"),
    DatasetSpec("departments", Path("departments.csv"), "csv", "Кафедры и факультеты"),
    DatasetSpec("educational_programs", Path("educational_programs.csv"), "csv", "Образовательные программы кафедр"),
    DatasetSpec("entrance_subjects", Path("entrance_subjects.csv"), "csv", "Вступительные предметы, минимальные баллы и выборность"),
    DatasetSpec("historical_passing_scores", Path("historical_passing_scores.csv"), "csv", "Исторические проходные баллы"),
    DatasetSpec("tuition", Path("tuition.csv"), "csv", "Стоимость обучения"),
    DatasetSpec("study_plan_files", Path("study_plan_files.csv"), "csv", "Связи программ с файлами учебных планов"),
    DatasetSpec("study_plan_documents", Path("study_plan_data/study_plan_documents.jsonl"), "jsonl", "Канонические скачанные документы учебных планов"),
    DatasetSpec("study_plan_pages", Path("study_plan_data/study_plan_pages.jsonl"), "jsonl", "Страницы, слова и координаты PDF"),
    DatasetSpec("study_plan_tables", Path("study_plan_data/study_plan_tables.jsonl"), "jsonl", "Обнаруженные таблицы учебных планов"),
    DatasetSpec("study_plan_rows", Path("study_plan_data/study_plan_rows.jsonl"), "jsonl", "Все строки таблиц и ссылки на ячейки"),
    DatasetSpec("study_plan_curriculum_rows", Path("study_plan_data/study_plan_curriculum_rows.jsonl"), "jsonl", "Семантически разобранные строки curriculum"),
    DatasetSpec("study_plan_disciplines", Path("study_plan_data/study_plan_disciplines.jsonl"), "jsonl", "Дисциплины и общая нагрузка"),
    DatasetSpec("study_plan_discipline_entities", Path("study_plan_data/study_plan_discipline_entities.jsonl"), "jsonl", "Детерминированный индекс повторяющихся дисциплин"),
    DatasetSpec("study_plan_semester_load", Path("study_plan_data/study_plan_semester_load.csv"), "csv", "Нагрузка дисциплин по семестрам"),
    DatasetSpec("study_plan_cells", Path("study_plan_data/study_plan_cells.csv"), "csv", "Полный канонический набор исходных PDF-ячеек"),
)

_SPECS_BY_NAME = {spec.name: spec for spec in DATASET_SPECS}


class DatasetRepository:
    """Read-only, line-oriented access to parser outputs.

    Files are intentionally not loaded into memory in full. This matters for
    ``study_plan_cells.csv`` and ``study_plan_ontology.json``-sized datasets.
    """

    def __init__(self, result_dir: Path) -> None:
        self.result_dir = result_dir

    def spec(self, name: str) -> DatasetSpec:
        try:
            return _SPECS_BY_NAME[name]
        except KeyError as exc:
            raise DatasetNotFoundError(f"Неизвестный dataset: {name}") from exc

    def path_for(self, name: str) -> Path:
        return self.result_dir / self.spec(name).relative_path

    def descriptors(self) -> list[dict[str, Any]]:
        result = []
        for spec in DATASET_SPECS:
            path = self.result_dir / spec.relative_path
            result.append(
                {
                    "name": spec.name,
                    "format": spec.format,
                    "path": str(spec.relative_path).replace("\\", "/"),
                    "description": spec.description,
                    "available": path.exists(),
                    "size_bytes": path.stat().st_size if path.exists() else None,
                }
            )
        return result

    def iter_rows(self, name: str) -> Iterator[dict[str, Any]]:
        spec = self.spec(name)
        path = self.result_dir / spec.relative_path
        if not path.exists():
            raise DatasetUnavailableError(f"Dataset ещё не создан: {path}")
        if spec.format == "csv":
            with path.open(encoding="utf-8-sig", newline="") as stream:
                yield from csv.DictReader(stream)
            return
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    yield json.loads(line)

    @staticmethod
    def _matches(row: dict[str, Any], filters: dict[str, str], query: str | None) -> bool:
        for field, expected in filters.items():
            if expected and str(row.get(field, "")) != expected:
                return False
        if query:
            serialized = json.dumps(row, ensure_ascii=False, default=str).casefold()
            if query.casefold() not in serialized:
                return False
        return True

    def page(
        self,
        name: str,
        *,
        offset: int,
        limit: int,
        filters: dict[str, str] | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        if offset < 0 or limit < 1:
            raise ValueError("offset должен быть >= 0, limit должен быть > 0")
        filters = filters or {}
        total = 0
        items: list[dict[str, Any]] = []
        for row in self.iter_rows(name):
            if not self._matches(row, filters, query):
                continue
            if total >= offset and len(items) < limit:
                items.append(row)
            total += 1
        return {
            "dataset": name,
            "items": items,
            "offset": offset,
            "limit": limit,
            "total": total,
            "has_more": offset + len(items) < total,
        }

    def first(self, name: str, field: str, value: str) -> dict[str, Any] | None:
        for row in self.iter_rows(name):
            if str(row.get(field, "")) == value:
                return row
        return None

    def reports(self) -> dict[str, Any]:
        report_paths = {
            "parse": self.result_dir / "parse_report.json",
            "study_plan_extraction": self.result_dir / "study_plan_data/study_plan_extraction_report.json",
            "study_plan_semantics": self.result_dir / "study_plan_data/study_plan_semantic_report.json",
            "study_plan_resolution": self.result_dir / "study_plan_data/study_plan_resolution_report.json",
        }
        result: dict[str, Any] = {}
        for name, path in report_paths.items():
            if path.exists():
                result[name] = json.loads(path.read_text(encoding="utf-8"))
        return result

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the newest persisted pipeline run manifests."""

        run_dir = self.result_dir / "pipeline_runs"
        if not run_dir.exists():
            return []
        manifests: list[dict[str, Any]] = []
        for path in sorted(run_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            if path.name == "latest.json":
                continue
            try:
                manifests.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
            if len(manifests) >= limit:
                break
        return manifests

    def run(self, run_id: str) -> dict[str, Any] | None:
        if not run_id or Path(run_id).name != run_id or Path(run_id).suffix:
            return None
        path = self.result_dir / "pipeline_runs" / f"{run_id}.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def quality_passed(self) -> bool | None:
        reports = self.reports()
        if not reports:
            return None
        values = [report.get("verification", {}).get("passed") for report in reports.values()]
        known = [value for value in values if value is not None]
        return all(known) if known else None

    def document_file(self, document_id: str) -> tuple[Path, str, str] | None:
        document = self.first("study_plan_documents", "document_id", document_id)
        if not document:
            return None
        allowed_root = (self.result_dir / "study_plans").resolve()
        candidates = []
        if document.get("absolute_path"):
            candidates.append(Path(str(document["absolute_path"])))
        if document.get("local_path"):
            candidates.append(self.result_dir / str(document["local_path"]))
        for candidate in candidates:
            resolved = candidate.resolve()
            try:
                resolved.relative_to(allowed_root)
            except ValueError:
                continue
            if resolved.is_file():
                content_type = document.get("expected_mime_type") or mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
                return resolved, resolved.name, content_type
        return None
