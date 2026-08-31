"""Neutral extractor facade kept under the core namespace."""

from ...sources.docx import DocxExtractor
from ...sources.pdf import PdfExtractor
from ...sources.xlsx import XlsxExtractor

__all__ = ["DocxExtractor", "PdfExtractor", "XlsxExtractor"]
