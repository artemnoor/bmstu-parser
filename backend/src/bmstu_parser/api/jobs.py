from __future__ import annotations

import logging
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
    """Single-writer operation queue backed by a pluggable durable store."""

    def __init__(self, *, store: JobStore | None = None) -> None:
        self.store = store or InMemoryJobStore()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="bmstu-api-operation"
        )
        self._lock = RLock()
        self._active_id: str | None = None

    def submit(
        self, operation: str, task: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        with self._lock:
            self.store.prune()
            active = self.store.active()
            if active:
                raise OperationConflictError(
                    f"Уже выполняется операция {active['operation']} ({active['id']})"
                )
            identifier = uuid4().hex
            record = {
                "id": identifier,
                "operation": operation,
                "status": "queued",
                "submitted_at_utc": utc_now(),
                "started_at_utc": None,
                "finished_at_utc": None,
                "result": None,
                "error": None,
            }
            self.store.create(record)
            self._active_id = identifier
            try:
                self._executor.submit(self._run, identifier, task)
            except Exception as exc:
                self.store.update(
                    identifier,
                    status="failed",
                    finished_at_utc=utc_now(),
                    error=f"{type(exc).__name__}: {exc}",
                )
                self._active_id = None
                raise
            return record

    def _run(self, identifier: str, task: Callable[[], dict[str, Any]]) -> None:
        self.store.update(identifier, status="running", started_at_utc=utc_now())
        try:
            result = task()
        except Exception as exc:
            LOGGER.exception("BMSTU API operation %s failed", identifier)
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
        finally:
            with self._lock:
                if self._active_id == identifier:
                    self._active_id = None

    def get(self, identifier: str) -> dict[str, Any] | None:
        return self.store.get(identifier)

    def shutdown(self) -> None:
        # Wait for a running task before closing a durable store. Otherwise a
        # worker can race with SQLite.close() while publishing its final state.
        self._executor.shutdown(wait=True, cancel_futures=True)
        self.store.close()
