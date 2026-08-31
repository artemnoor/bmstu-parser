from __future__ import annotations

from pathlib import Path
from typing import Any

from bmstu_parser.study_plans.compact import compact_existing_dataset
from bmstu_parser.study_plans.pipeline import StudyPlanExtractionPipeline
from bmstu_parser.study_plans.semantics import enrich_existing_dataset

from ..core.registry import UniversityRegistry
from ..pipeline import PipelineOptions, UniversityPipeline
from .models import OperationRequest


class OperationQualityError(RuntimeError):
    def __init__(self, operation: str, result: dict[str, Any]) -> None:
        self.result = result
        super().__init__(f"Quality gate failed for operation {operation}")


def execute_operation(
    request: OperationRequest,
    result_root: Path,
    university_id: str,
    registry: UniversityRegistry,
) -> dict[str, Any]:
    result_dir = result_root / university_id
    if request.operation == "refresh":
        report = UniversityPipeline(registry).run(
            university_id,
            PipelineOptions(
                output_dir=result_root,
                workers=request.workers,
                page_size=request.page_size,
                timeout=request.timeout,
                delay=request.delay,
                resolve_plans=request.resolve_plans,
                download_plans=request.download_plans,
                strict=False,
            ),
        )
    elif request.operation == "extract_study_plans":
        report = StudyPlanExtractionPipeline(
            result_dir,
            workers=request.workers,
            reader_backend=request.reader_backend,
            resume=request.resume,
        ).run()
    elif request.operation == "extract_semantics":
        report = enrich_existing_dataset(result_dir)
    elif request.operation == "compact_study_plans":
        report = compact_existing_dataset(result_dir)
    else:  # pragma: no cover
        raise ValueError(f"Unsupported operation: {request.operation}")
    result = {
        "operation": request.operation,
        "university_id": university_id,
        "quality": report,
    }
    if request.strict and not report.get("verification", {}).get("passed", False):
        raise OperationQualityError(request.operation, result)
    return result
