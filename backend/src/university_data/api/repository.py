from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


DATASET_SPECS = (
    DatasetSpec(
        "universities",
        Path("canonical/universities.csv"),
        "csv",
        "Канонические университеты",
    ),
    DatasetSpec(
        "faculties",
        Path("canonical/faculties.csv"),
        "csv",
        "Канонические факультеты",
    ),
    DatasetSpec(
        "study_directions",
        Path("canonical/study_directions.csv"),
        "csv",
        "Канонические направления подготовки",
    ),
    DatasetSpec(
        "programs",
        Path("canonical/programs.csv"),
        "csv",
        "Канонические образовательные программы",
    ),
    DatasetSpec(
        "curricula",
        Path("canonical/curricula.csv"),
        "csv",
        "Канонические учебные планы",
    ),
    DatasetSpec("teachers", Path("canonical/teachers.csv"), "csv", "Преподаватели"),
    DatasetSpec(
        "admission", Path("canonical/admission.csv"), "csv", "Вступительные требования"
    ),
    DatasetSpec(
        "admission_requirements",
        Path("canonical/admission_requirements.csv"),
        "csv",
        "Канонические вступительные требования",
    ),
    DatasetSpec(
        "tuition_options",
        Path("canonical/tuition_options.csv"),
        "csv",
        "Канонические варианты стоимости обучения",
    ),
    DatasetSpec(
        "disciplines", Path("canonical/disciplines.csv"), "csv", "Дисциплины и нагрузка"
    ),
    DatasetSpec("semesters", Path("canonical/semesters.csv"), "csv", "Семестры"),
    DatasetSpec(
        "semester_loads",
        Path("canonical/semester_loads.csv"),
        "csv",
        "Нагрузка по семестрам",
    ),
    DatasetSpec(
        "semantic_disciplines",
        Path("semantic/study_plan_disciplines.jsonl"),
        "jsonl",
        "Семантические дисциплины, извлечённые из учебных планов",
    ),
    DatasetSpec(
        "semantic_semester_loads",
        Path("semantic/study_plan_semester_loads.jsonl"),
        "jsonl",
        "Семантическая семестровая нагрузка",
    ),
    DatasetSpec(
        "majors", Path("majors.csv"), "csv", "Совместимый projection направлений"
    ),
    DatasetSpec("departments", Path("departments.csv"), "csv", "Кафедры"),
    DatasetSpec(
        "educational_programs",
        Path("educational_programs.csv"),
        "csv",
        "Совместимый projection программ",
    ),
    DatasetSpec(
        "study_plan_files",
        Path("study_plan_files.csv"),
        "csv",
        "Связи программ с файлами планов",
    ),
    DatasetSpec(
        "study_plan_documents",
        Path("study_plan_data/study_plan_documents.jsonl"),
        "jsonl",
        "Документы учебных планов",
    ),
    DatasetSpec(
        "study_plan_curriculum_rows",
        Path("study_plan_data/study_plan_curriculum_rows.jsonl"),
        "jsonl",
        "Семантические строки curriculum",
    ),
    DatasetSpec(
        "study_plan_disciplines",
        Path("study_plan_data/study_plan_disciplines.jsonl"),
        "jsonl",
        "Дисциплины из PDF",
    ),
    DatasetSpec(
        "study_plan_cells",
        Path("study_plan_data/study_plan_cells.csv"),
        "csv",
        "Исходные PDF-ячеек",
    ),
)
_BY_NAME = {item.name: item for item in DATASET_SPECS}
_FALLBACKS = {
    "programs": (Path("educational_programs.csv"), "csv"),
    "curricula": (
        Path("study_plan_data/study_plan_curriculum_rows.jsonl"),
        "jsonl",
    ),
    "admission": (Path("entrance_subjects.csv"), "csv"),
    "admission_requirements": (Path("entrance_subjects.csv"), "csv"),
    "disciplines": (
        Path("study_plan_data/study_plan_disciplines.jsonl"),
        "jsonl",
    ),
    "tuition_options": (Path("tuition.csv"), "csv"),
}


class DatasetRepository:
    def __init__(self, result_root: Path, university_id: str) -> None:
        if Path(university_id).name != university_id or university_id in {
            "",
            ".",
            "..",
        }:
            raise ValueError("Invalid university namespace")
        self.result_dir = result_root / university_id
        self.university_id = university_id

    def spec(self, name: str) -> DatasetSpec:
        try:
            return _BY_NAME[name]
        except KeyError as exc:
            raise DatasetNotFoundError(f"Unknown dataset: {name}") from exc

    def path_for(self, name: str) -> Path:
        primary = self.result_dir / self.spec(name).relative_path
        if primary.is_file():
            return primary
        fallback = _FALLBACKS.get(name)
        return self.result_dir / fallback[0] if fallback else primary

    def format_for(self, name: str) -> str:
        path = self.path_for(name)
        fallback = _FALLBACKS.get(name)
        if fallback and path == self.result_dir / fallback[0]:
            return fallback[1]
        return self.spec(name).format

    def descriptors(self) -> list[dict[str, Any]]:
        result = []
        for spec in DATASET_SPECS:
            path = self.path_for(spec.name)
            result.append(
                {
                    "name": spec.name,
                    "format": self.format_for(spec.name),
                    "path": str(path.relative_to(self.result_dir)).replace("\\", "/"),
                    "description": spec.description,
                    "available": path.is_file(),
                    "size_bytes": path.stat().st_size if path.is_file() else None,
                }
            )
        return result

    def _aliases(self) -> dict[str, str]:
        path = self.result_dir / "id_aliases.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {
            str(item.get("legacy_id")): str(item.get("canonical_id"))
            for item in payload.get("aliases", [])
            if isinstance(item, dict)
            and item.get("legacy_id")
            and item.get("canonical_id")
        }

    def resolve_alias(self, value: str) -> str:
        aliases = self._aliases()
        seen: set[str] = set()
        while value in aliases and value not in seen:
            seen.add(value)
            value = aliases[value]
        return value

    def iter_rows(self, name: str) -> Iterator[dict[str, Any]]:
        self.spec(name)
        path = self.path_for(name)
        if not path.is_file():
            raise DatasetUnavailableError(f"Dataset is not published: {name}")
        if self.format_for(name) == "jsonl":
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    if line.strip():
                        value = json.loads(line)
                        if isinstance(value, dict):
                            yield value
            return
        with path.open(encoding="utf-8-sig", newline="") as stream:
            yield from csv.DictReader(stream)

    def page(
        self,
        name: str,
        *,
        offset: int,
        limit: int,
        filters: dict[str, str] | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        filters = dict(filters or {})
        if "id" in filters:
            filters["id"] = self.resolve_alias(filters["id"])
        items: list[dict[str, Any]] = []
        for row in self.iter_rows(name):
            if any(
                str(row.get(key, "")) != str(value) for key, value in filters.items()
            ):
                continue
            if (
                query
                and query.casefold()
                not in json.dumps(row, ensure_ascii=False, default=str).casefold()
            ):
                continue
            items.append(dict(row))
        return {
            "dataset": name,
            "items": items[offset : offset + limit],
            "offset": offset,
            "limit": limit,
            "total": len(items),
            "has_more": offset + limit < len(items),
        }

    def reports(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for relative in (
            "quality/report.json",
            "parse_report.json",
            "study_plan_data/study_plan_extraction_report.json",
        ):
            path = self.result_dir / relative
            if path.is_file():
                try:
                    result[path.stem] = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
        return result

    def quality_passed(self) -> bool | None:
        values = [
            item.get("verification", {}).get("passed")
            for item in self.reports().values()
        ]
        known = [item for item in values if isinstance(item, bool)]
        return all(known) if known else None

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        directory = self.result_dir / "pipeline_runs"
        result = []
        for path in (
            sorted(
                directory.glob("*.json"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            if directory.is_dir()
            else []
        ):
            if path.name == "latest.json":
                continue
            try:
                result.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
            if len(result) >= limit:
                break
        return result
