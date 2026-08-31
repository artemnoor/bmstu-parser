from __future__ import annotations

import csv
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from ..domain.ids import stable_id
from ..runtime.atomic import atomic_write_json
from ..runtime.checkpoints import CheckpointStore, file_fingerprint
from ..runtime.lineage import PipelineRun
from .models import StudyPlanReference
from .ontology import StudyPlanOntologyBuilder
from .quality import validate_extractions
from .reader import extract_document
from .readers import DocumentReader, get_reader_backend
from .writers import write_extraction_dataset

LOGGER = logging.getLogger(__name__)


def _int_or_none(value: str) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _reference_from_row(row: dict[str, str]) -> StudyPlanReference:
    local_path = str(row.get("local_path", "")).replace("\\", "/")
    return StudyPlanReference(
        document_id=row.get("id") or stable_id("study-plan-document", local_path),
        local_path=local_path,
        major_id=row.get("major_id", ""),
        major_slug=row.get("major_slug", ""),
        major_code=row.get("major_code", ""),
        major_name=row.get("major_name", ""),
        program_id=row.get("program_id", ""),
        program_code=row.get("program_code", ""),
        program_name=row.get("program_name", ""),
        plan_url=row.get("plan_url", ""),
        plan_status=row.get("plan_status", ""),
        source_url=row.get("source_url", ""),
        resolved_url=row.get("resolved_url", ""),
        expected_size=_int_or_none(row.get("size", "")),
        expected_sha256=row.get("sha256", ""),
        expected_mime_type=row.get("mime_type", ""),
    )


def _reference_dict(reference: StudyPlanReference) -> dict[str, Any]:
    return {
        "document_id": reference.document_id,
        "local_path": reference.local_path,
        "major_id": reference.major_id,
        "major_slug": reference.major_slug,
        "major_code": reference.major_code,
        "major_name": reference.major_name,
        "program_id": reference.program_id,
        "program_code": reference.program_code,
        "program_name": reference.program_name,
        "plan_url": reference.plan_url,
        "plan_status": reference.plan_status,
        "source_url": reference.source_url,
        "resolved_url": reference.resolved_url,
        "expected_size": reference.expected_size,
        "expected_sha256": reference.expected_sha256,
        "expected_mime_type": reference.expected_mime_type,
    }


class StudyPlanExtractionPipeline:
    def __init__(
        self,
        result_dir: Path,
        workers: int = 4,
        *,
        reader_backend: str | DocumentReader = "native",
        resume: bool = True,
    ) -> None:
        self.result_dir = result_dir
        self.workers = max(1, workers)
        self.reader_backend = get_reader_backend(reader_backend)
        self.resume = resume
        self.reference_groups: dict[str, list[StudyPlanReference]] = {}
        self.manifest_references: list[StudyPlanReference] = []
        self.invalid_references: list[dict[str, Any]] = []

    def _load_references(self) -> list[StudyPlanReference]:
        manifest = self.result_dir / "study_plan_files.csv"
        if not manifest.exists():
            raise FileNotFoundError(f"Не найден манифест учебных планов: {manifest}")
        references: list[StudyPlanReference] = []
        with manifest.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                reference = _reference_from_row(row)
                self.manifest_references.append(reference)
                if not reference.local_path:
                    self.invalid_references.append(
                        {
                            "document_id": reference.document_id,
                            "program_id": reference.program_id,
                            "plan_url": reference.plan_url,
                            "error": "В манифесте отсутствует local_path",
                        }
                    )
                    continue
                # One public document can be referenced by several programs.
                # Extract it once by its source identity and retain every
                # program reference for ontology links.
                if reference.document_id not in self.reference_groups:
                    self.reference_groups[reference.document_id] = []
                    references.append(reference)
                self.reference_groups[reference.document_id].append(reference)
        return references

    def _checkpoint_result_path(self, reference: StudyPlanReference) -> Path:
        safe_id = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in reference.document_id
        )
        return self.result_dir / "study_plan_data" / "checkpoints" / f"{safe_id}.json"

    def _extract_one(
        self, reference: StudyPlanReference, checkpoints: CheckpointStore
    ) -> dict[str, Any]:
        source_path = self.result_dir / Path(reference.local_path.replace("\\", "/"))
        fingerprint = file_fingerprint(
            source_path,
            reference.document_id,
            reference.local_path,
            reference.expected_size,
            reference.expected_sha256,
            self.reader_backend.name,
        )
        if self.resume:
            hit = checkpoints.get(reference.document_id, fingerprint)
            if hit is not None:
                try:
                    cached = json.loads(hit.result_path.read_text(encoding="utf-8"))
                    if isinstance(cached, dict) and isinstance(
                        cached.get("document"), dict
                    ):
                        return cached
                except (OSError, json.JSONDecodeError):
                    LOGGER.warning(
                        "Повреждён checkpoint учебного плана: %s", hit.result_path
                    )

        result = extract_document(
            reference, self.result_dir, reader_backend=self.reader_backend
        )
        result_path = self._checkpoint_result_path(reference)
        atomic_write_json(result_path, result)
        checkpoints.mark(
            reference.document_id,
            fingerprint,
            result_path,
            status=str(result.get("document", {}).get("status", "unknown")),
        )
        return result

    def run(self) -> dict[str, Any]:
        run = PipelineRun(self.result_dir, "extract_study_plans")
        try:
            references = self._load_references()
            root = self.result_dir
            checkpoints = CheckpointStore(root / "study_plan_data" / "checkpoints")
            results: list[dict[str, Any] | None] = [None] * len(references)
            with ThreadPoolExecutor(
                max_workers=self.workers, thread_name_prefix="bmstu-plan"
            ) as pool:
                futures = {
                    pool.submit(self._extract_one, reference, checkpoints): index
                    for index, reference in enumerate(references)
                }
                for completed, future in enumerate(as_completed(futures), start=1):
                    index = futures[future]
                    result = future.result()
                    # A physical document may be referenced by more than one program.
                    result["document"]["source_references"] = [
                        _reference_dict(reference)
                        for reference in self.reference_groups[
                            references[index].document_id
                        ]
                    ]
                    results[index] = result
                    if completed % 10 == 0 or completed == len(references):
                        LOGGER.info(
                            "Учебные планы: обработано %s/%s",
                            completed,
                            len(references),
                        )
            materialized = [result for result in results if result is not None]
            all_rows = [
                row
                for result in materialized
                for table in result.get("tables", [])
                for row in table.get("rows", [])
            ]
            all_cells = [cell for row in all_rows for cell in row]
            physical_files = [
                path.relative_to(root)
                for path in (root / "study_plans").rglob("*")
                if path.is_file()
            ]
            quality = validate_extractions(
                references,
                materialized,
                physical_files,
                len(all_rows),
                len(all_cells),
                all_references=self.manifest_references,
                invalid_references=self.invalid_references,
            )
            ontology = StudyPlanOntologyBuilder().build(materialized)
            write_extraction_dataset(
                root / "study_plan_data", materialized, quality, ontology
            )
            run.stage(
                "extract_documents",
                inputs=["study_plan_files.csv", "study_plans"],
                outputs=[
                    "study_plan_data/study_plan_documents.jsonl",
                    "study_plan_data/study_plan_pages.jsonl",
                    "study_plan_data/study_plan_tables.jsonl",
                    "study_plan_data/study_plan_rows.jsonl",
                    "study_plan_data/study_plan_cells.csv",
                ],
                metadata={
                    "documents": len(materialized),
                    "workers": self.workers,
                    "reader_backend": self.reader_backend.name,
                    "resume": self.resume,
                    "checkpoint_file": "study_plan_data/checkpoints/study_plan_checkpoints.json",
                },
            )
            run.stage(
                "quality_gate",
                inputs=[
                    "study_plan_data/study_plan_documents.jsonl",
                    "study_plan_data/study_plan_tables.jsonl",
                    "study_plan_data/study_plan_rows.jsonl",
                    "study_plan_data/study_plan_cells.csv",
                ],
                outputs=["study_plan_data/study_plan_extraction_report.json"],
                quality=quality,
            )
            run.finish(quality=quality)
            return quality
        except Exception as exc:
            run.finish(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
