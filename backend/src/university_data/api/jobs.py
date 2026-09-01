from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from typing import Any
from uuid import uuid4

from .job_store import InMemoryJobStore, JobStore, utc_now

LOGGER = logging.getLogger(__name__)


class OperationConflictError(RuntimeError):
    pass


class JobManager:
    """University-scoped operation queue backed by a durable store."""

    def __init__(self, *, store: JobStore | None = None, max_workers: int = 4) -> None:
        self.store = store or InMemoryJobStore()
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, max_workers),
            thread_name_prefix="university-api-operation",
        )
        self._lock = RLock()

    def submit(
        self,
        operation: str,
        task: Callable[[], dict[str, Any]],
        *,
        university_id: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            self.store.prune()
            active = self.store.active(university_id)
            if active:
                raise OperationConflictError(
                    f"Для {university_id or 'университета'} уже выполняется операция "
                    f"{active['operation']} ({active['id']})"
                )
            identifier = uuid4().hex
            record = {
                "id": identifier,
                "university_id": university_id,
                "operation": operation,
                "status": "queued",
                "submitted_at_utc": utc_now(),
                "started_at_utc": None,
                "finished_at_utc": None,
                "result": None,
                "error": None,
            }
            try:
                self.store.create(record)
            except sqlite3.IntegrityError as exc:
                active = self.store.active(university_id)
                if active:
                    raise OperationConflictError(
                        f"Для {university_id or 'университета'} уже выполняется операция "
                        f"{active['operation']} ({active['id']})"
                    ) from exc
                raise
            try:
                self._executor.submit(self._run, identifier, task)
            except Exception as exc:
                self.store.update(
                    identifier,
                    status="failed",
                    finished_at_utc=utc_now(),
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise
            return record

    def _run(self, identifier: str, task: Callable[[], dict[str, Any]]) -> None:
        self.store.update(identifier, status="running", started_at_utc=utc_now())
        try:
            result = task()
        except Exception as exc:
            LOGGER.exception("University API operation %s failed", identifier)
            self.store.update(
                identifier,
                status="failed",
                finished_at_utc=utc_now(),
                error=f"{type(exc).__name__}: {exc}",
                result=getattr(exc, "result", None),
            )
        else:
            self.store.update(
                identifier,
                status="succeeded",
                finished_at_utc=utc_now(),
                result=result,
            )

    def get(self, identifier: str) -> dict[str, Any] | None:
        return self.store.get(identifier)

    def shutdown(self) -> None:
        # Wait for a running task before closing a durable store. Otherwise a
        # worker can race with SQLite.close() while publishing its final state.
        self._executor.shutdown(wait=True, cancel_futures=True)
        self.store.close()
