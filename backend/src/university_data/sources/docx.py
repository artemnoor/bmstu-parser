"""DOCX extraction facade for the shared document reader."""

from pathlib import Path

from bmstu_parser.study_plans.readers import ReaderResult

from .documents import NativeDocumentReader


class DocxExtractor:
    """Extract a DOCX through the platform's native reader seam."""

    def __init__(self) -> None:
        self._reader = NativeDocumentReader()

    def extract(self, path: Path, document_id: str = "docx") -> ReaderResult:
        if path.suffix.casefold() != ".docx":
            raise ValueError(f"Expected a DOCX path, got {path.name}")
        return self._reader.extract(path, document_id)


__all__ = ["DocxExtractor"]
