from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PipelineRun:
    """Persist a small, local build history for the parser pipeline.

    The interface is intentionally narrow: a pipeline declares completed
    stages and their input/output artifacts, while this module records stable
    run identity, timestamps, file fingerprints, quality results, and errors.
    This is the local equivalent of a dataset build/lineage record; it does
    not pretend to be a Foundry runtime.
    """

    def __init__(
        self, result_dir: Path, pipeline: str, *, parent_run_id: str | None = None
    ) -> None:
        self.result_dir = result_dir
        self.run_id = uuid4().hex
        self._manifest_dir = result_dir / "pipeline_runs"
        self._path = self._manifest_dir / f"{self.run_id}.json"
        self._record: dict[str, Any] = {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "pipeline": pipeline,
            "parent_run_id": parent_run_id,
            "status": "running",
            "started_at_utc": _now(),
            "finished_at_utc": None,
            "stages": [],
            "quality": None,
            "error": None,
        }
        self._persist()

    @property
    def path(self) -> Path:
        return self._path

    @staticmethod
    def _reference(value: str | Path, root: Path) -> dict[str, Any]:
        reference = str(value).replace("\\", "/")
        if "://" in reference:
            return {"ref": reference, "kind": "external", "available": True}

        path = Path(value)
        if not path.is_absolute():
            path = root / path
        try:
            relative = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            relative = str(path.resolve()).replace("\\", "/")
        artifact: dict[str, Any] = {
            "ref": relative,
            "kind": "dataset",
            "available": path.exists(),
        }
        if path.is_file():
            artifact["size_bytes"] = path.stat().st_size
            artifact["sha256"] = _sha256(path)
        elif path.is_dir():
            files = [item for item in path.rglob("*") if item.is_file()]
            artifact["file_count"] = len(files)
            artifact["size_bytes"] = sum(item.stat().st_size for item in files)
        return artifact

    def stage(
        self,
        name: str,
        *,
        inputs: Iterable[str | Path] = (),
        outputs: Iterable[str | Path] = (),
        quality: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._record["stages"].append(
            {
                "name": name,
                "status": "succeeded",
                "completed_at_utc": _now(),
                "inputs": [self._reference(item, self.result_dir) for item in inputs],
                "outputs": [self._reference(item, self.result_dir) for item in outputs],
                "quality": quality,
                "metadata": metadata or {},
            }
        )
        self._persist()

    def finish(
        self,
        *,
        status: str = "succeeded",
        quality: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self._record["status"] = status
        self._record["finished_at_utc"] = _now()
        self._record["quality"] = quality
        self._record["error"] = error
        self._persist()

    def _persist(self) -> None:
        self._manifest_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f".json.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(self._record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self._path)
        latest = self._manifest_dir / "latest.json"
        latest_payload = {
            "run_id": self.run_id,
            "pipeline": self._record["pipeline"],
            "status": self._record["status"],
            "manifest": self._path.name,
            "updated_at_utc": self._record["finished_at_utc"]
            or self._record["started_at_utc"],
        }
        latest_temporary = latest.with_suffix(f".json.{os.getpid()}.tmp")
        latest_temporary.write_text(
            json.dumps(latest_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        latest_temporary.replace(latest)
