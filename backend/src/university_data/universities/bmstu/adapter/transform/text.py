from __future__ import annotations

import html
import json
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any, ClassVar
from urllib.parse import urljoin

from ..domain.types import json_default


class _HTMLTextParser(HTMLParser):
    BLOCK_TAGS: ClassVar[frozenset[str]] = frozenset(
        {
            "address",
            "article",
            "aside",
            "blockquote",
            "br",
            "div",
            "dl",
            "dt",
            "dd",
            "figcaption",
            "figure",
            "footer",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "li",
            "main",
            "nav",
            "ol",
            "p",
            "pre",
            "section",
            "table",
            "tr",
            "ul",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    parser = _HTMLTextParser()
    try:
        parser.feed(text)
        parser.close()
        text = "".join(parser.parts)
    # HTMLParser is intentionally best-effort for source fields from external APIs.
    except Exception:  # noqa: BLE001
        text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    lines: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def first_text(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "да"}:
        return True
    if text in {"0", "false", "no", "нет"}:
        return False
    return None


def normalize_url(value: Any, base: str = "https://mirror.bmstu.ru") -> str:
    if not value:
        return ""
    return urljoin(base, str(value).strip())


def clean_slug(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"[^\w.-]+", "_", text, flags=re.UNICODE)
    return text.strip("._")[:180] or "file"


def safe_filename(value: Any, fallback: str = "file") -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text or fallback)[:220]


def json_cell(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), default=json_default
    )
