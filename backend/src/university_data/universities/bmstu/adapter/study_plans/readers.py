"""BMSTU study-plan facade over the shared document reader contract."""

from university_data.sources.readers import (
    DoclingDocumentReader,
    DocumentReader,
    NativeDocumentReader,
    ReaderResult,
    get_reader_backend,
)

__all__ = [
    "DoclingDocumentReader",
    "DocumentReader",
    "NativeDocumentReader",
    "ReaderResult",
    "get_reader_backend",
]
