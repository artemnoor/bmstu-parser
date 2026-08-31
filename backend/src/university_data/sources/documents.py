"""PDF/DOCX reader seam shared by university plugins."""

from .readers import (
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
