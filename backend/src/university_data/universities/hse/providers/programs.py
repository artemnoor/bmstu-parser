from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from ....core.source_models import SourceProgram
from ....domain.ids import canonical_source_key
from ....domain.provenance import SourceProvenance
from ....runtime.atomic import atomic_write_text
from ....sources.http import ApiClient

SOURCE_PAGE = "https://www.hse.ru/n/education/bachelor"
CODE_RE = re.compile(r"\b(?P<code>\d{2}\.\d{2}\.\d{2})\b")


class _CatalogParser(HTMLParser):
    """Extract only the stable public catalog card fields from HSE HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, str]] = []
        self.next_url = ""
        self._card: dict[str, str] | None = None
        self._field: str | None = None
        self._field_tag: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set(str(values.get("class", "")).split())
        if tag == "link" and "next" in str(values.get("rel", "")).split():
            self.next_url = str(values.get("href", ""))
        if tag == "a" and "e-card" in classes:
            self._card = {"href": str(values.get("href", ""))}
        if self._card is None:
            return
        if "e-card__category" in classes:
            self._field, self._field_tag, self._buffer = "category", tag, []
        elif "e-card__title-inner" in classes:
            self._field, self._field_tag, self._buffer = "title", tag, []

    def handle_data(self, data: str) -> None:
        if self._card is not None and self._field is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if (
            self._field is not None
            and tag == self._field_tag
            and self._card is not None
        ):
            self._card[self._field] = " ".join("".join(self._buffer).split())
            self._field = None
            self._field_tag = None
            self._buffer = []
        if tag == "a" and self._card is not None:
            if self._card.get("href"):
                self.cards.append(self._card)
            self._card = None


class HseProgramsProvider:
    capability = "programs"
    persists_raw = True

    def __init__(self, options: Any, client: ApiClient | None = None) -> None:
        self.client = client or ApiClient(
            timeout=float(options.timeout),
            delay=float(options.delay),
            user_agent="university-data-platform/hse-adapter",
        )
        self.output_dir = Path(options.output_dir) / "hse" / "raw"

    def fetch(self) -> list[SourceProgram]:
        result: list[SourceProgram] = []
        seen_program_urls: set[str] = set()
        url = SOURCE_PAGE
        visited: set[str] = set()
        page_number = 0
        while url and url not in visited:
            visited.add(url)
            page_number += 1
            html = self.client.get_text(url)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(
                self.output_dir / f"catalog-page-{page_number}.html", html
            )
            parser = _CatalogParser()
            parser.feed(html)
            for card in parser.cards:
                category = card.get("category", "")
                title = card.get("title", "")
                match = CODE_RE.search(category)
                code = match.group("code") if match else ""
                name = title or category[match.end() :].strip() if match else title
                if not name:
                    continue
                direction_name = (
                    category[match.end() :].strip() or name if match else name
                )
                href = urljoin(url, card["href"])
                stable_href = canonical_source_key(href)
                if stable_href in seen_program_urls:
                    continue
                seen_program_urls.add(stable_href)
                result.append(
                    SourceProgram(
                        source_key=stable_href,
                        name=name,
                        code=code,
                        study_direction_key=code or name,
                        raw={
                            "category": category,
                            "catalog_url": href,
                            "catalog_page": url,
                            "study_direction_name": direction_name,
                            "study_direction_code": code,
                        },
                        provenance=SourceProvenance(
                            source_page=SOURCE_PAGE,
                            detail_page=href,
                            raw_snapshot_path=f"raw/catalog-page-{page_number}.html",
                            source_key=stable_href,
                        ),
                    )
                )
            next_url = parser.next_url
            url = urljoin(url, next_url) if next_url else ""
        return result


__all__ = ["SOURCE_PAGE", "HseProgramsProvider"]
