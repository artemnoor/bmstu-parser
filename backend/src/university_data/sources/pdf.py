"""PDF extraction facade for the shared document reader."""

from pathlib import Path

from bmstu_parser.study_plans.readers import ReaderResult

from .documents import NativeDocumentReader


class PdfExtractor:
    """Extract a PDF through the platform's native reader seam."""

    def __init__(self) -> None:
        self._reader = NativeDocumentReader()

    def extract(self, path: Path, document_id: str = "pdf") -> ReaderResult:
        if path.suffix.casefold() != ".pdf":
            raise ValueError(f"Expected a PDF path, got {path.name}")
        return self._reader.extract(path, document_id)


__all__ = ["PdfExtractor"]
