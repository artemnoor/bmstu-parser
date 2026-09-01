from __future__ import annotations

import csv
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..runtime.atomic import atomic_text_writer, atomic_write_json


class UniversityStorage:
    """Safe, namespaced result layout for one registered university.

    A pipeline writes into a run-scoped candidate storage and publishes it by
    atomically replacing a small ``current.json`` pointer.  The pointer is the
    authoritative read view; direct files under the university directory are
    kept as a compatibility view for existing local consumers.
    """

    POINTER_NAME = "current.json"
    SNAPSHOT_DIR = ".snapshots"
    STAGING_DIR = ".staging"

    def __init__(self, root: Path, university_id: str) -> None:
        if (
            not university_id
            or university_id in {".", ".."}
            or Path(university_id).name != university_id
        ):
            raise ValueError("Invalid university_id for storage namespace")
        self.root = root
        self.university_id = university_id
        self.path = root / university_id

    def candidate(self, run_id: str) -> UniversityStorage:
        """Return an isolated candidate namespace for one pipeline run."""

        if not run_id or Path(run_id).name != run_id:
            raise ValueError("Invalid run_id for staging namespace")
        return UniversityStorage(
            self.root / self.STAGING_DIR / run_id, self.university_id
        )

    def active_path(self) -> Path:
        """Return the last successfully published snapshot, or legacy path."""

        pointer = self.path / self.POINTER_NAME
        try:
            payload = json.loads(pointer.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self.path
        relative = payload.get("snapshot") if isinstance(payload, dict) else None
        if not isinstance(relative, str) or not relative:
            return self.path
        snapshot = (self.path / relative).resolve()
        try:
            snapshot.relative_to(self.path.resolve())
        except ValueError:
            return self.path
        return snapshot if snapshot.is_dir() else self.path

    def is_published(self) -> bool:
        active = self.active_path()
        return active != self.path and active.is_dir()

    def ensure(self) -> Path:
        for name in ("raw", "canonical", "semantic", "quality", "pipeline_runs"):
            (self.path / name).mkdir(parents=True, exist_ok=True)
        return self.path

    def discard(self) -> None:
        """Remove this storage only when it is a staging namespace."""

        if self.root.parent.name != self.STAGING_DIR:
            return
        if self.path.is_dir():
            shutil.rmtree(self.path)
        if self.root.is_dir() and not any(self.root.iterdir()):
            self.root.rmdir()

    def publish(self, candidate: UniversityStorage, run_id: str) -> Path:
        """Atomically make a validated candidate the active snapshot."""

        if not run_id or Path(run_id).name != run_id:
            raise ValueError("Invalid run_id for published snapshot")
        if candidate.university_id != self.university_id:
            raise ValueError("Candidate university does not match storage namespace")
        expected_staging = (self.root / self.STAGING_DIR).resolve()
        if candidate.root.parent.resolve() != expected_staging:
            raise ValueError("Candidate is outside this storage staging namespace")
        if candidate.root.name != run_id:
            raise ValueError("Candidate run_id does not match the published snapshot")
        candidate_path = candidate.path
        if not candidate_path.is_dir():
            raise FileNotFoundError(f"Candidate snapshot is missing: {candidate_path}")

        self.path.mkdir(parents=True, exist_ok=True)
        snapshots = self.path / self.SNAPSHOT_DIR
        snapshots.mkdir(parents=True, exist_ok=True)
        snapshot = snapshots / run_id
        if snapshot.exists():
            raise FileExistsError(f"Snapshot already exists: {snapshot}")
        candidate_path.replace(snapshot)

        try:
            atomic_write_json(
                self.path / self.POINTER_NAME,
                {
                    "schema_version": "1.0",
                    "run_id": run_id,
                    "snapshot": f"{self.SNAPSHOT_DIR}/{run_id}",
                    "published_at_utc": datetime.now(UTC).isoformat(),
                },
            )
        except Exception:
            shutil.rmtree(snapshot, ignore_errors=True)
            raise
        try:
            self._materialize_compatibility_view(snapshot)
        except OSError:
            # The pointer is authoritative.  A failed compatibility copy must
            # not turn a successfully published snapshot into a failed run.
            pass
        candidate.discard()
        return snapshot

    def read_canonical_records(self) -> dict[str, list[dict[str, Any]]]:
        """Read the active JSONL canonical datasets for alias generation."""

        result: dict[str, list[dict[str, Any]]] = {}
        directory = self.active_path() / "canonical"
        if not directory.is_dir():
            return result
        for path in directory.glob("*.jsonl"):
            rows: list[dict[str, Any]] = []
            try:
                with path.open(encoding="utf-8") as stream:
                    for line in stream:
                        if line.strip():
                            value = json.loads(line)
                            if isinstance(value, dict):
                                rows.append(value)
            except (OSError, json.JSONDecodeError):
                continue
            result[path.stem] = rows
        return result

    def read_aliases(self) -> list[dict[str, Any]]:
        path = self.active_path() / "id_aliases.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        aliases = payload.get("aliases") if isinstance(payload, dict) else None
        return (
            [item for item in aliases if isinstance(item, dict)]
            if isinstance(aliases, list)
            else []
        )

    def _materialize_compatibility_view(self, snapshot: Path) -> None:
        """Keep legacy direct paths usable; active snapshot remains authoritative."""

        self.path.mkdir(parents=True, exist_ok=True)
        for source in snapshot.iterdir():
            if source.name == "pipeline_runs":
                continue
            target = self.path / source.name
            if source.is_dir():
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
                shutil.copytree(source, target)
            else:
                if target.is_dir():
                    shutil.rmtree(target)
                temporary = target.with_suffix(target.suffix + ".tmp")
                shutil.copy2(source, temporary)
                temporary.replace(target)

    def write_json(self, relative: str, payload: Any) -> None:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(target, payload)

    def write_jsonl(self, relative: str, rows: list[dict[str, Any]]) -> None:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with atomic_text_writer(target, encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def write_csv(self, relative: str, rows: list[dict[str, Any]]) -> None:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        fields = sorted({key for row in rows for key in row})
        with atomic_text_writer(target, encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(
                {key: "" if value is None else value for key, value in row.items()}
                for row in rows
            )
