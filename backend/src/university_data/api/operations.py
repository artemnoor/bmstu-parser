from __future__ import annotations

from pathlib import Path
from typing import Any

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
    """Execute a scoped operation through the generic pipeline or plugin seam."""

    plugin = registry.require(university_id)
    result_dir = result_root / plugin.university_id
    if request.operation == "refresh":
        report = UniversityPipeline(registry).run(
            plugin.university_id,
            PipelineOptions(
                output_dir=result_root,
                workers=request.workers,
                page_size=request.page_size,
                timeout=request.timeout,
                delay=request.delay,
                resolve_plans=request.resolve_plans,
                download_plans=request.download_plans,
                reader_backend=request.reader_backend,
                strict=False,
            ),
        )
    else:
        report = plugin.operations().execute(request, result_dir)
    result = {
        "operation": request.operation,
        "university_id": plugin.university_id,
        "quality": report,
    }
    if request.strict and not report.get("verification", {}).get("passed", False):
        raise OperationQualityError(request.operation, result)
    return result
