# mypy: ignore-errors

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from university_data.core.sources.http import ApiClient, FetchError

from ..config import DETAIL_ENDPOINT, LIST_ENDPOINT


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class DetailFetch:
    summary: dict[str, Any]
    detail: dict[str, Any] | None
    error: str | None
    fetched_at_utc: str


class MirrorApi:
    def __init__(
        self, client: ApiClient, workers: int = 6, page_size: int = 100
    ) -> None:
        self.client = client
        self.workers = max(1, workers)
        self.page_size = max(1, page_size)

    def fetch_major_list(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        meta: dict[str, Any] = {}
        while True:
            payload = self.client.get_json(
                LIST_ENDPOINT,
                params={"limit": self.page_size, "offset": offset},
            )
            page = [item for item in payload.get("data", []) if isinstance(item, dict)]
            current_meta = (
                payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            )
            meta.update(current_meta)
            items.extend(page)
            if not page:
                break
            total = current_meta.get("count")
            if isinstance(total, int) and offset + len(page) >= total:
                break
            if len(page) < self.page_size:
                break
            offset += len(page)
        return items, meta

    def fetch_detail(self, summary: dict[str, Any]) -> DetailFetch:
        slug = str(summary.get("slug", ""))
        try:
            detail = self.client.get_json(
                DETAIL_ENDPOINT.format(slug=quote(slug, safe=""))
            )
            return DetailFetch(summary, detail, None, utc_now())
        except FetchError as exc:
            return DetailFetch(summary, None, str(exc), utc_now())

    def fetch_details(self, summaries: list[dict[str, Any]]) -> list[DetailFetch]:
        if not summaries:
            return []
        if self.workers == 1:
            return [self.fetch_detail(summary) for summary in summaries]

        result: list[DetailFetch | None] = [None] * len(summaries)
        with ThreadPoolExecutor(
            max_workers=self.workers, thread_name_prefix="bmstu-detail"
        ) as pool:
            futures = {
                pool.submit(self.fetch_detail, summary): index
                for index, summary in enumerate(summaries)
            }
            for future in as_completed(futures):
                index = futures[future]
                result[index] = future.result()
        return [item for item in result if item is not None]
