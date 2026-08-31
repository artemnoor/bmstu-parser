"""Neutral extractor facade kept under the core namespace."""

from ...sources.docx import DocxExtractor
from ...sources.http import ApiClient, FetchError, RateLimiter
from ...sources.json import read_json
from ...sources.pdf import PdfExtractor
from ...sources.xlsx import XlsxExtractor
from ...sources.yandex import PublicFile, PublicFileResolver, PublicFiles

__all__ = [
    "ApiClient",
    "DocxExtractor",
    "FetchError",
    "PdfExtractor",
    "PublicFile",
    "PublicFileResolver",
    "PublicFiles",
    "RateLimiter",
    "XlsxExtractor",
    "read_json",
]
