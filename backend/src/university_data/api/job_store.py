from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, ClassVar, Protocol


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class JobStore(Protocol):
    def create(self, record: dict[str, Any]) -> None: ...

    def get(self, identifier: str) -> dict[str, Any] | None: ...

    def update(self, identifier: str, **changes: Any) -> None: ...

    def active(self, university_id: str | None = None) -> dict[str, Any] | None: ...

    def prune(self) -> None: ...

    def close(self) -> None: ...


class InMemoryJobStore:
    """Deterministic store used by unit tests and explicitly local callers."""

    def __init__(
        self, *, max_records: int = 1000, ttl_seconds: int = 30 * 24 * 60 * 60
    ) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._lock = RLock()
        self.max_records = max(1, max_records)
        self.ttl_seconds = max(1, ttl_seconds)

    def create(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._records[str(record["id"])] = deepcopy(record)

    def get(self, identifier: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._records.get(identifier)
            return deepcopy(value) if value is not None else None

    def update(self, identifier: str, **changes: Any) -> None:
        with self._lock:
            if identifier in self._records:
                self._records[identifier].update(deepcopy(changes))

    def active(self, university_id: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            active = [
                record
                for record in self._records.values()
                if record["status"] in {"queued", "running"}
                and (
                    university_id is None
                    or record.get("university_id", "") == university_id
                )
            ]
            if not active:
                return None
            active.sort(key=lambda record: record["submitted_at_utc"])
            return deepcopy(active[0])

    def prune(self) -> None:
        with self._lock:
            cutoff = datetime.now(UTC) - timedelta(seconds=self.ttl_seconds)
            for identifier, record in list(self._records.items()):
                if record["status"] in {"queued", "running"}:
                    continue
                timestamp = record.get("finished_at_utc") or record.get(
                    "submitted_at_utc"
                )
                try:
                    expired = datetime.fromisoformat(str(timestamp)) < cutoff
                except (TypeError, ValueError):
                    expired = False
                if expired:
                    del self._records[identifier]
            completed = [
                record
                for record in self._records.values()
                if record["status"] not in {"queued", "running"}
            ]
            completed.sort(
                key=lambda record: (
                    record.get("finished_at_utc") or record["submitted_at_utc"]
                ),
                reverse=True,
            )
            for record in completed[self.max_records :]:
                self._records.pop(str(record["id"]), None)

    def close(self) -> None:
        return None


class SqliteJobStore:
    """Persistent operation status store with restart recovery and retention."""

    _UPDATABLE: ClassVar[frozenset[str]] = frozenset(
        {
            "status",
            "started_at_utc",
            "finished_at_utc",
            "result",
            "error",
        }
    )

    def __init__(
        self,
        path: Path,
        *,
        max_records: int = 1000,
        ttl_seconds: int = 30 * 24 * 60 * 60,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_records = max(1, max_records)
        self.ttl_seconds = max(1, ttl_seconds)
        self._lock = RLock()
        self._connection = sqlite3.connect(
            self.path, timeout=30, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute("PRAGMA busy_timeout=30000")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY,
                university_id TEXT NOT NULL DEFAULT '',
                operation TEXT NOT NULL,
                status TEXT NOT NULL,
                submitted_at_utc TEXT NOT NULL,
                started_at_utc TEXT,
                finished_at_utc TEXT,
                result_json TEXT,
                error TEXT
            )
            """
        )
        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(operations)")
        }
        if "university_id" not in columns:
            self._connection.execute(
                "ALTER TABLE operations ADD COLUMN university_id TEXT NOT NULL DEFAULT ''"
            )
        self._connection.commit()
        self._recover_interrupted()
        self._connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS operations_one_active_per_university
            ON operations(university_id)
            WHERE status IN ('queued', 'running')
            """
        )
        self._connection.commit()
        self.prune()

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        result: Any = None
        if row["result_json"]:
            try:
                result = json.loads(row["result_json"])
            except json.JSONDecodeError:
                result = None
        return {
            "id": row["id"],
            "university_id": row["university_id"],
            "operation": row["operation"],
            "status": row["status"],
            "submitted_at_utc": row["submitted_at_utc"],
            "started_at_utc": row["started_at_utc"],
            "finished_at_utc": row["finished_at_utc"],
            "result": result,
            "error": row["error"],
        }

    def _recover_interrupted(self) -> None:
        with self._lock:
            self._connection.execute(
                """
                UPDATE operations
                SET status = 'failed',
                    finished_at_utc = ?,
                    error = ?
                WHERE status IN ('queued', 'running')
                """,
                (utc_now(), "Операция прервана перезапуском API-процесса"),
            )
            self._connection.commit()

    def create(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO operations
                    (id, university_id, operation, status, submitted_at_utc, started_at_utc,
                     finished_at_utc, result_json, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record.get("university_id", ""),
                    record["operation"],
                    record["status"],
                    record["submitted_at_utc"],
                    record.get("started_at_utc"),
                    record.get("finished_at_utc"),
                    json.dumps(record.get("result"), ensure_ascii=False)
                    if record.get("result") is not None
                    else None,
                    record.get("error"),
                ),
            )
            self._connection.commit()

    def get(self, identifier: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM operations WHERE id = ?", (identifier,)
            ).fetchone()
            return self._decode(row) if row else None

    def update(self, identifier: str, **changes: Any) -> None:
        unexpected = set(changes) - self._UPDATABLE
        if unexpected:
            raise ValueError(f"Недопустимые поля операции: {sorted(unexpected)}")
        if not changes:
            return
        assignments: list[str] = []
        parameters: list[Any] = []
        for field, value in changes.items():
            if field == "result":
                assignments.append("result_json = ?")
                parameters.append(
                    json.dumps(value, ensure_ascii=False) if value is not None else None
                )
            else:
                assignments.append(f"{field} = ?")
                parameters.append(value)
        parameters.append(identifier)
        with self._lock:
            self._connection.execute(
                f"UPDATE operations SET {', '.join(assignments)} WHERE id = ?",
                parameters,
            )
            self._connection.commit()

    def active(self, university_id: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            query = "SELECT * FROM operations WHERE status IN ('queued', 'running') "
            parameters: tuple[str, ...] = ()
            if university_id is not None:
                query += "AND university_id = ? "
                parameters = (university_id,)
            query += "ORDER BY submitted_at_utc LIMIT 1"
            row = self._connection.execute(query, parameters).fetchone()
            return self._decode(row) if row else None

    def prune(self) -> None:
        cutoff = (datetime.now(UTC) - timedelta(seconds=self.ttl_seconds)).isoformat()
        with self._lock:
            self._connection.execute(
                "DELETE FROM operations WHERE status IN ('succeeded', 'failed') AND COALESCE(finished_at_utc, submitted_at_utc) < ?",
                (cutoff,),
            )
            self._connection.execute(
                """
                DELETE FROM operations
                WHERE status IN ('succeeded', 'failed')
                  AND id NOT IN (
                    SELECT id FROM operations
                    WHERE status IN ('succeeded', 'failed')
                    ORDER BY COALESCE(finished_at_utc, submitted_at_utc) DESC
                    LIMIT ?
                  )
                """,
                (self.max_records,),
            )
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()
