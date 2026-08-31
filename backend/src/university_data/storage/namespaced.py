from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ..runtime.atomic import atomic_text_writer, atomic_write_json


class UniversityStorage:
    """Safe, namespaced result layout for one registered university."""

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

    def ensure(self) -> Path:
        for name in ("raw", "canonical", "semantic", "quality", "pipeline_runs"):
            (self.path / name).mkdir(parents=True, exist_ok=True)
        return self.path

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
