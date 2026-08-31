from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import Settings
from ..pipeline import ScrapePipeline
from ..study_plans.compact import compact_existing_dataset
from ..study_plans.pipeline import StudyPlanExtractionPipeline
from ..study_plans.semantics import enrich_existing_dataset
from .models import OperationRequest


class OperationQualityError(RuntimeError):
    def __init__(self, operation: str, result: dict[str, Any]) -> None:
        self.result = result
        super().__init__(f"Quality gate не пройден для операции {operation}")


def _quality_result(
    operation: str, report: dict[str, Any], strict: bool
) -> dict[str, Any]:
    result = {"operation": operation, "quality": report}
    if strict and not report.get("verification", {}).get("passed", False):
        raise OperationQualityError(operation, result)
    return result


def execute_operation(request: OperationRequest, result_dir: Path) -> dict[str, Any]:
    if request.operation == "refresh":
        report = ScrapePipeline(
            Settings(
                output_dir=result_dir,
                workers=request.workers,
                page_size=request.page_size,
                timeout=request.timeout,
                delay=request.delay,
                resolve_plans=request.resolve_plans,
                download_plans=request.download_plans,
                strict=request.strict,
            )
        ).run()
        return _quality_result(request.operation, report, request.strict)
    if request.operation == "extract_study_plans":
        report = StudyPlanExtractionPipeline(
            result_dir,
            workers=request.workers,
            reader_backend=request.reader_backend,
            resume=request.resume,
        ).run()
        return _quality_result(request.operation, report, request.strict)
    if request.operation == "extract_semantics":
        report = enrich_existing_dataset(result_dir)
        return _quality_result(request.operation, report, request.strict)
    if request.operation == "compact_study_plans":
        report = compact_existing_dataset(result_dir)
        return _quality_result(request.operation, report, request.strict)
    raise ValueError(f"Неподдерживаемая операция: {request.operation}")
