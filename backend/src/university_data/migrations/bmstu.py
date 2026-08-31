from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ..core.registry import UniversityRegistry
from ..domain.ids import global_stable_id
from ..pipeline import PipelineOptions, UniversityPipeline
from ..runtime.atomic import atomic_write_json
from ..universities.bmstu.adapter.ingestion.mirror_api import DetailFetch
from ..universities.bmstu.adapter.transform.normalize import Normalizer
from ..universities.bmstu.plugin import BmstuPlugin, BmstuSourceSnapshot


class BmstuRawReplayProvider:
    """Read a captured BMSTU raw snapshot without network access."""

    def __init__(self, source_dir: Path) -> None:
        self.source_dir = source_dir

    def fetch(self) -> tuple[list[dict[str, Any]], dict[str, Any], list[DetailFetch]]:
        payload = json.loads(
            (self.source_dir / "raw" / "majors_list.json").read_text(encoding="utf-8")
        )
        summaries = [item for item in payload.get("data", []) if isinstance(item, dict)]
        meta = (
            dict(payload.get("meta", {}))
            if isinstance(payload.get("meta"), dict)
            else {}
        )
        details: list[DetailFetch] = []
        for path in sorted((self.source_dir / "raw" / "details").glob("*.json")):
            item = json.loads(path.read_text(encoding="utf-8"))
            details.append(
                DetailFetch(
                    item.get("summary", {}),
                    item.get("detail"),
                    item.get("error"),
                    str(item.get("fetched_at_utc", "")),
                )
            )
        return summaries, meta, details


def _global_aliases(majors: list[Any]) -> list[dict[str, str]]:
    aliases: dict[str, tuple[str, str]] = {}
    for major in majors:
        direction_key = major.slug or major.code or major.name
        aliases[major.id] = (
            "study_direction",
            global_stable_id("bmstu", "study_direction", direction_key),
        )
        for department in major.departments:
            key = department.slug or department.code or department.name
            aliases[department.id] = (
                "department",
                global_stable_id("bmstu", "department", key),
            )
            for program in department.educational_programs:
                key = program.code or program.name or program.id
                aliases[program.id] = (
                    "program",
                    global_stable_id("bmstu", "program", key),
                )
        for requirement in major.entrance_requirements:
            aliases[requirement.id] = (
                "admission_requirement",
                global_stable_id(
                    "bmstu",
                    "admission_requirement",
                    direction_key,
                    requirement.subject,
                    requirement.id,
                ),
            )
        for option in major.tuition:
            aliases[option.id] = (
                "tuition_option",
                global_stable_id(
                    "bmstu",
                    "tuition_option",
                    direction_key,
                    option.study_form,
                    option.term,
                    option.id,
                ),
            )
    return [
        {
            "legacy_id": legacy,
            "canonical_id": canonical,
            "entity_type": entity_type,
        }
        for legacy, (entity_type, canonical) in sorted(aliases.items())
        if legacy != canonical
    ]


def migrate_bmstu(
    source_dir: Path,
    target_dir: Path,
    *,
    rebuild_derived: bool = True,
    write_aliases: bool = True,
) -> dict[str, Any]:
    """Rebuild a namespaced BMSTU catalog from raw files, then restore bytes."""

    source_dir = source_dir.resolve()
    target_dir = target_dir.resolve()
    raw_dir = source_dir / "raw"
    if not (raw_dir / "majors_list.json").is_file():
        raise FileNotFoundError(f"Не найден raw snapshot BMSTU: {raw_dir}")

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    quality: dict[str, Any] = {
        "verification": {"passed": True},
        "university_id": "bmstu",
    }
    if rebuild_derived:
        plugin = BmstuPlugin(replay_dir=source_dir)
        registry = UniversityRegistry((plugin,))
        quality = UniversityPipeline(registry).run(
            "bmstu",
            PipelineOptions(
                output_dir=target_dir.parent,
                resolve_plans=False,
                download_plans=False,
                strict=False,
            ),
        )

    majors: list[Any] = []
    if write_aliases:
        snapshot = BmstuSourceSnapshot(
            PipelineOptions(output_dir=target_dir.parent, resolve_plans=False),
            replay_dir=source_dir,
        )
        snapshot._load_replay(source_dir)
        majors = [Normalizer().normalize(item) for item in snapshot.details]
    # Raw is immutable evidence. The replay may have normalized JSON while it
    # was being read, so copy the original bytes back after derived rebuild.
    shutil.copytree(raw_dir, target_dir / "raw", dirs_exist_ok=True)
    # Study-plan documents/checkpoints are also source evidence. They cannot
    # be reconstructed from the API JSON alone, so keep them alongside the
    # rebuilt platform projection when the legacy catalog contains them.
    for relative in ("study_plan_files.csv", "study_plans", "study_plan_data"):
        source = source_dir / relative
        target = target_dir / relative
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    if write_aliases:
        atomic_write_json(
            target_dir / "id_aliases.json",
            {"schema_version": "2.0", "aliases": _global_aliases(majors)},
        )
    return {
        **quality,
        "migration": {
            "replayed": True,
            "source_dir": str(source_dir),
            "target_dir": str(target_dir),
            "raw_preserved": True,
            "aliases": len(_global_aliases(majors)) if write_aliases else 0,
            "rebuild_derived": rebuild_derived,
        },
    }
