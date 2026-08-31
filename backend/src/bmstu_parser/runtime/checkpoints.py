from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json


def file_fingerprint(path: Path, *parts: object) -> str:
    """Return a deterministic fingerprint for a source and its contract."""

    payload: dict[str, Any] = {
        "parts": [str(part) for part in parts],
        "exists": path.exists(),
    }
    if path.exists():
        stat = path.stat()
        payload["size"] = stat.st_size
        payload["mtime_ns"] = stat.st_mtime_ns
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CheckpointHit:
    key: str
    fingerprint: str
    result_path: Path
    status: str


class CheckpointStore:
    """Small, thread-safe, resumable ledger for document extraction.

    The ledger stores only a source fingerprint and a path to a materialized
    result. It never treats a stale result as valid and it does not mutate
    canonical data itself.
    """

    def __init__(self, directory: Path, filename: str = "study_plan_checkpoints.json") -> None:
        self.directory = directory
        self.path = directory / filename
        self._lock = threading.RLock()
        self._records: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        records = payload.get("records") if isinstance(payload, dict) else None
        if isinstance(records, dict):
            self._records = {str(key): value for key, value in records.items() if isinstance(value, dict)}

    def _persist(self) -> None:
        atomic_write_json(
            self.path,
            {
                "schema_version": "1.0",
                "records": self._records,
            },
        )

    def get(self, key: str, fingerprint: str) -> CheckpointHit | None:
        with self._lock:
            record = self._records.get(key)
            if not record or record.get("fingerprint") != fingerprint:
                return None
            stored_path = Path(str(record.get("result_path", "")))
            result_path = stored_path if stored_path.is_absolute() else self.directory / stored_path
            if not result_path.is_file():
                return None
            return CheckpointHit(
                key=key,
                fingerprint=fingerprint,
                result_path=result_path,
                status=str(record.get("status", "unknown")),
            )

    def mark(
        self,
        key: str,
        fingerprint: str,
        result_path: Path,
        *,
        status: str,
    ) -> None:
        with self._lock:
            resolved_result_path = result_path.resolve()
            resolved_directory = self.directory.resolve()
            try:
                stored_result_path = resolved_result_path.relative_to(resolved_directory).as_posix()
            except ValueError:
                # Keep the API useful for callers that materialize results
                # outside the ledger directory (the extraction pipeline keeps
                # them inside it, so normal records remain relocatable).
                stored_result_path = str(resolved_result_path)
            self._records[key] = {
                "fingerprint": fingerprint,
                "result_path": stored_result_path,
                "status": status,
            }
            self._persist()
