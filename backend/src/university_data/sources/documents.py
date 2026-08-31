"""PDF/DOCX reader seam shared by university plugins."""

from bmstu_parser.study_plans.readers import (
    DoclingDocumentReader,
    DocumentReader,
    NativeDocumentReader,
    get_reader_backend,
)

__all__ = [
    "DoclingDocumentReader",
    "DocumentReader",
    "NativeDocumentReader",
    "get_reader_backend",
]
