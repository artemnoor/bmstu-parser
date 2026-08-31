from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable
from uuid import uuid4


LOGGER = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OperationConflictError(RuntimeError):
    pass


class JobManager:
    """Small in-process operation queue for the early-release service.

    Only one mutating parser operation runs at a time. This prevents two
    writers from rebuilding the same result directory concurrently.
    """

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bmstu-api-operation")
        self._lock = RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._active_id: str | None = None

    def submit(self, operation: str, task: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            if self._active_id:
                active = self._jobs.get(self._active_id)
                if active and active["status"] in {"queued", "running"}:
                    raise OperationConflictError(f"Уже выполняется операция {active['operation']} ({active['id']})")
            identifier = uuid4().hex
            record = {
                "id": identifier,
                "operation": operation,
                "status": "queued",
                "submitted_at_utc": _now(),
                "started_at_utc": None,
                "finished_at_utc": None,
                "result": None,
                "error": None,
            }
            self._jobs[identifier] = record
            self._active_id = identifier
            self._executor.submit(self._run, identifier, task)
            return dict(record)

    def _run(self, identifier: str, task: Callable[[], dict[str, Any]]) -> None:
        with self._lock:
            record = self._jobs[identifier]
            record["status"] = "running"
            record["started_at_utc"] = _now()
        try:
            result = task()
        except Exception as exc:  # noqa: BLE001 - operation status must be observable through the API.
            LOGGER.exception("BMSTU API operation %s failed", identifier)
            with self._lock:
                record = self._jobs[identifier]
                record["status"] = "failed"
                record["finished_at_utc"] = _now()
                record["error"] = f"{type(exc).__name__}: {exc}"
                record["result"] = getattr(exc, "result", None)
                self._active_id = None
            return
        with self._lock:
            record = self._jobs[identifier]
            record["status"] = "succeeded"
            record["finished_at_utc"] = _now()
            record["result"] = result
            self._active_id = None

    def get(self, identifier: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._jobs.get(identifier)
            return dict(record) if record else None

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
