from __future__ import annotations

import csv
import importlib
import json
import mimetypes
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import duckdb
except ImportError:  # pragma: no cover - exercised only in minimal local installs.
    duckdb = None  # type: ignore[assignment]


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
    DatasetSpec(
        "majors", Path("majors.csv"), "csv", "Направления подготовки и их свойства"
    ),
    DatasetSpec("departments", Path("departments.csv"), "csv", "Кафедры и факультеты"),
    DatasetSpec(
        "educational_programs",
        Path("educational_programs.csv"),
        "csv",
        "Образовательные программы кафедр",
    ),
    DatasetSpec(
        "entrance_subjects",
        Path("entrance_subjects.csv"),
        "csv",
        "Вступительные предметы, минимальные баллы и выборность",
    ),
    DatasetSpec(
        "historical_passing_scores",
        Path("historical_passing_scores.csv"),
        "csv",
        "Исторические проходные баллы",
    ),
    DatasetSpec("tuition", Path("tuition.csv"), "csv", "Стоимость обучения"),
    DatasetSpec(
        "study_plan_files",
        Path("study_plan_files.csv"),
        "csv",
        "Связи программ с файлами учебных планов",
    ),
    DatasetSpec(
        "study_plan_documents",
        Path("study_plan_data/study_plan_documents.jsonl"),
        "jsonl",
        "Канонические скачанные документы учебных планов",
    ),
    DatasetSpec(
        "study_plan_pages",
        Path("study_plan_data/study_plan_pages.jsonl"),
        "jsonl",
        "Страницы, слова и координаты PDF",
    ),
    DatasetSpec(
        "study_plan_tables",
        Path("study_plan_data/study_plan_tables.jsonl"),
        "jsonl",
        "Обнаруженные таблицы учебных планов",
    ),
    DatasetSpec(
        "study_plan_rows",
        Path("study_plan_data/study_plan_rows.jsonl"),
        "jsonl",
        "Все строки таблиц и ссылки на ячейки",
    ),
    DatasetSpec(
        "study_plan_curriculum_rows",
        Path("study_plan_data/study_plan_curriculum_rows.jsonl"),
        "jsonl",
        "Семантически разобранные строки curriculum",
    ),
    DatasetSpec(
        "study_plan_disciplines",
        Path("study_plan_data/study_plan_disciplines.jsonl"),
        "jsonl",
        "Дисциплины и общая нагрузка",
    ),
    DatasetSpec(
        "study_plan_discipline_entities",
        Path("study_plan_data/study_plan_discipline_entities.jsonl"),
        "jsonl",
        "Детерминированный индекс повторяющихся дисциплин",
    ),
    DatasetSpec(
        "study_plan_semester_load",
        Path("study_plan_data/study_plan_semester_load.csv"),
        "csv",
        "Нагрузка дисциплин по семестрам",
    ),
    DatasetSpec(
        "study_plan_cells",
        Path("study_plan_data/study_plan_cells.csv"),
        "csv",
        "Полный канонический набор исходных PDF-ячеек",
    ),
)

_SPECS_BY_NAME = {spec.name: spec for spec in DATASET_SPECS}


class _DatasetReader:
    """Shared catalog, aliases, report and secure-file behavior."""

    engine = "file"

    def __init__(self, result_dir: Path) -> None:
        self.result_dir = result_dir
        self._aliases: dict[str, str] = {}
        self._aliases_state: tuple[int, int] | None = None
        self._refresh_aliases()

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
        raise NotImplementedError

    def page(
        self,
        name: str,
        *,
        offset: int,
        limit: int,
        filters: dict[str, str] | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def first(self, name: str, field: str, value: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def _load_aliases(self) -> dict[str, str]:
        path = self.result_dir / "id_aliases.json"
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        aliases = payload.get("aliases", []) if isinstance(payload, dict) else []
        result: dict[str, str] = {}
        for item in aliases:
            if not isinstance(item, dict):
                continue
            legacy_id = str(item.get("legacy_id") or "")
            canonical_id = str(item.get("canonical_id") or "")
            if legacy_id and canonical_id:
                result[legacy_id] = canonical_id
        return result

    def _refresh_aliases(self) -> None:
        path = self.result_dir / "id_aliases.json"
        try:
            stat = path.stat()
            state = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            state = None
        if state == self._aliases_state:
            return
        self._aliases = self._load_aliases() if state is not None else {}
        self._aliases_state = state

    def resolve_alias(self, value: str) -> str:
        self._refresh_aliases()
        current = value
        seen: set[str] = set()
        while current in self._aliases and current not in seen:
            seen.add(current)
            current = self._aliases[current]
        return current

    def reports(self) -> dict[str, Any]:
        report_paths = {
            "parse": self.result_dir / "parse_report.json",
            "study_plan_extraction": self.result_dir
            / "study_plan_data/study_plan_extraction_report.json",
            "study_plan_semantics": self.result_dir
            / "study_plan_data/study_plan_semantic_report.json",
            "study_plan_resolution": self.result_dir
            / "study_plan_data/study_plan_resolution_report.json",
        }
        result: dict[str, Any] = {}
        for name, path in report_paths.items():
            if path.exists():
                try:
                    result[name] = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
        return result

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the newest persisted pipeline run manifests."""

        run_dir = self.result_dir / "pipeline_runs"
        if not run_dir.exists():
            return []
        manifests: list[dict[str, Any]] = []
        for path in sorted(
            run_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True
        ):
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
        values = [
            report.get("verification", {}).get("passed") for report in reports.values()
        ]
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
                content_type = (
                    document.get("expected_mime_type")
                    or mimetypes.guess_type(resolved.name)[0]
                    or "application/octet-stream"
                )
                return resolved, resolved.name, content_type
        return None


class FileDatasetReader(_DatasetReader):
    """Compatibility reader for old result directories and tiny fixtures."""

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

    def _matches(
        self, row: dict[str, Any], filters: dict[str, str], query: str | None
    ) -> bool:
        for field, expected in filters.items():
            canonical = self.resolve_alias(expected)
            actual = str(row.get(field, ""))
            legacy = str(row.get("legacy_id", ""))
            if actual != expected and actual != canonical and legacy != expected:
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
            expected = self.resolve_alias(value)
            if (
                str(row.get(field, "")) in {value, expected}
                or str(row.get("legacy_id", "")) == value
            ):
                return row
        return None


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _quote_path(path: Path) -> str:
    # The path is resolved from the fixed DatasetSpec allow-list, never from a
    # request parameter. Escaping is still required for valid Windows paths.
    return "'" + path.resolve().as_posix().replace("'", "''") + "'"


class DuckDBDatasetReader(_DatasetReader):
    """Vectorized SQL reader over the existing CSV/JSONL source of truth."""

    engine = "duckdb"

    def __init__(self, result_dir: Path) -> None:
        global duckdb
        if duckdb is None:  # pragma: no cover - dependency is pinned at runtime.
            try:
                duckdb = importlib.import_module("duckdb")
            except ImportError as exc:
                raise RuntimeError(
                    "DuckDB недоступен; установите зависимость duckdb или выберите BMSTU_DATA_ENGINE=file"
                ) from exc
        super().__init__(result_dir)
        self._schema_cache: dict[str, tuple[str, ...]] = {}

    def _source(self, spec: DatasetSpec, path: Path) -> str:
        quoted = _quote_path(path)
        if spec.format == "csv":
            return f"read_csv_auto({quoted}, header=true, all_varchar=true)"
        return f"read_json_auto({quoted}, format='newline_delimited')"

    def _connection(self) -> Any:
        assert duckdb is not None
        return duckdb.connect(database=":memory:")

    def _columns(self, connection: Any, source: str, cache_key: str) -> tuple[str, ...]:
        cached = self._schema_cache.get(cache_key)
        if cached is not None:
            return cached
        rows = connection.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()
        columns = tuple(str(row[0]) for row in rows)
        self._schema_cache[cache_key] = columns
        return columns

    def _where(
        self,
        filters: dict[str, str],
        query: str | None,
        columns: tuple[str, ...],
    ) -> tuple[str, list[str]]:
        predicates: list[str] = []
        parameters: list[str] = []
        available = set(columns)
        for field, expected in filters.items():
            if field not in available:
                return "FALSE", []
            canonical = self.resolve_alias(expected)
            values = [canonical]
            if canonical != expected:
                values.append(expected)
            column = f"CAST({_quote_identifier(field)} AS VARCHAR)"
            if len(values) == 1:
                predicates.append(f"{column} = ?")
            else:
                predicates.append(f"({column} = ? OR {column} = ?)")
            parameters.extend(values)
        if query:
            if not columns:
                return "FALSE", []
            searchable = ", ".join(
                f"COALESCE(CAST({_quote_identifier(column)} AS VARCHAR), '')"
                for column in columns
            )
            predicates.append(
                f"contains(lower(concat_ws(' ', {searchable})), lower(?))"
            )
            parameters.append(query)
        return (" AND ".join(predicates) if predicates else "TRUE"), parameters

    @staticmethod
    def _records(cursor: Any) -> list[dict[str, Any]]:
        columns = [str(item[0]) for item in cursor.description or []]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def _prepare(
        self, name: str
    ) -> tuple[DatasetSpec, Path, Any, str, tuple[str, ...]]:
        spec = self.spec(name)
        path = self.result_dir / spec.relative_path
        if not path.exists():
            raise DatasetUnavailableError(f"Dataset ещё не создан: {path}")
        connection = self._connection()
        source = self._source(spec, path)
        try:
            stat = path.stat()
            cache_key = f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"
            columns = self._columns(connection, source, cache_key)
        except Exception:
            connection.close()
            raise
        return spec, path, connection, source, columns

    def iter_rows(self, name: str) -> Iterator[dict[str, Any]]:
        empty_path = self.path_for(name)
        if empty_path.exists() and empty_path.stat().st_size == 0:
            return
        _spec, _path, connection, source, _columns = self._prepare(name)
        try:
            cursor = connection.execute(f"SELECT * FROM {source}")
            columns = [str(item[0]) for item in cursor.description or []]
            for row in cursor.fetchall():
                yield dict(zip(columns, row, strict=True))
        finally:
            connection.close()

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
        empty_path = self.path_for(name)
        if empty_path.exists() and empty_path.stat().st_size == 0:
            return {
                "dataset": name,
                "items": [],
                "offset": offset,
                "limit": limit,
                "total": 0,
                "has_more": False,
            }
        _spec, _path, connection, source, columns = self._prepare(name)
        try:
            where, parameters = self._where(filters or {}, query, columns)
            total_row = connection.execute(
                f"SELECT count(*) FROM {source} WHERE {where}", parameters
            ).fetchone()
            total = int(total_row[0]) if total_row else 0
            cursor = connection.execute(
                f"SELECT * FROM {source} WHERE {where} LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            )
            items = self._records(cursor)
        finally:
            connection.close()
        return {
            "dataset": name,
            "items": items,
            "offset": offset,
            "limit": limit,
            "total": total,
            "has_more": offset + len(items) < total,
        }

    def first(self, name: str, field: str, value: str) -> dict[str, Any] | None:
        empty_path = self.path_for(name)
        if empty_path.exists() and empty_path.stat().st_size == 0:
            return None
        _spec, _path, connection, source, columns = self._prepare(name)
        try:
            if field not in columns:
                return None
            expected = self.resolve_alias(value)
            column = f"CAST({_quote_identifier(field)} AS VARCHAR)"
            predicates = [f"{column} = ?"]
            parameters: list[str] = [expected]
            if expected != value:
                predicates.append(f"{column} = ?")
                parameters.append(value)
            if "legacy_id" in columns:
                predicates.append(
                    f"CAST({_quote_identifier('legacy_id')} AS VARCHAR) = ?"
                )
                parameters.append(value)
            cursor = connection.execute(
                f"SELECT * FROM {source} WHERE {' OR '.join(predicates)} LIMIT 1",
                parameters,
            )
            records = self._records(cursor)
            return records[0] if records else None
        finally:
            connection.close()


class DatasetRepository:
    """Facade selecting DuckDB by default and retaining a file fallback."""

    def __init__(self, result_dir: Path, engine: str | None = None) -> None:
        configured = (engine or os.getenv("BMSTU_DATA_ENGINE") or "duckdb").casefold()
        if configured == "file":
            reader: _DatasetReader = FileDatasetReader(result_dir)
        elif configured == "duckdb":
            try:
                reader = DuckDBDatasetReader(result_dir)
            except RuntimeError:
                reader = FileDatasetReader(result_dir)
        else:
            reader = FileDatasetReader(result_dir)
        self._reader = reader
        self.result_dir = result_dir
        self.engine = reader.engine

    def spec(self, name: str) -> DatasetSpec:
        return self._reader.spec(name)

    def path_for(self, name: str) -> Path:
        return self._reader.path_for(name)

    def descriptors(self) -> list[dict[str, Any]]:
        return self._reader.descriptors()

    def iter_rows(self, name: str) -> Iterator[dict[str, Any]]:
        return self._reader.iter_rows(name)

    def page(
        self,
        name: str,
        *,
        offset: int,
        limit: int,
        filters: dict[str, str] | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        return self._reader.page(
            name, offset=offset, limit=limit, filters=filters, query=query
        )

    def first(self, name: str, field: str, value: str) -> dict[str, Any] | None:
        return self._reader.first(name, field, value)

    def resolve_alias(self, value: str) -> str:
        return self._reader.resolve_alias(value)

    def reports(self) -> dict[str, Any]:
        return self._reader.reports()

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._reader.runs(limit=limit)

    def run(self, run_id: str) -> dict[str, Any] | None:
        return self._reader.run(run_id)

    def quality_passed(self) -> bool | None:
        return self._reader.quality_passed()

    def document_file(self, document_id: str) -> tuple[Path, str, str] | None:
        return self._reader.document_file(document_id)
