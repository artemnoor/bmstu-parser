from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from .http import ApiClient, FetchError

YANDEX_RESOURCE_ENDPOINT = "https://cloud-api.yandex.net/v1/disk/public/resources"


@dataclass(frozen=True, slots=True)
class PublicFile:
    name: str
    path: str
    download_url: str
    size: int | None = None
    mime_type: str = ""


@dataclass(frozen=True, slots=True)
class PublicFiles:
    url: str
    resolved_url: str
    status: str
    files: tuple[PublicFile, ...] = ()


class PublicFileResolver:
    """Resolve configurable Yandex public links without university knowledge."""

    def __init__(
        self,
        client: ApiClient,
        *,
        resource_endpoint: str = YANDEX_RESOURCE_ENDPOINT,
        short_hosts: tuple[str, ...] = ("clck.ru", "clck.su"),
    ) -> None:
        self.client = client
        self.resource_endpoint = resource_endpoint
        self.short_hosts = short_hosts

    @staticmethod
    def _is_public_url(url: str) -> bool:
        host = urlparse(url).netloc.lower().split(":", 1)[0]
        return host.endswith(("yandex.ru", "yandex.com", "yadi.sk"))

    def _resource(
        self, public_url: str, *, path: str | None = None, offset: int = 0
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "public_key": public_url,
            "limit": 100,
            "offset": offset,
        }
        if path:
            params["path"] = path
        return self.client.get_json(self.resource_endpoint, params=params)

    def _files(self, public_url: str) -> list[dict[str, Any]]:
        first = self._resource(public_url)
        if first.get("type") == "file":
            return [first]
        result: list[dict[str, Any]] = []
        visited: set[str] = set()

        def walk(path: str, depth: int = 0) -> None:
            if depth > 8 or path in visited:
                return
            visited.add(path)
            offset = 0
            while True:
                page = self._resource(public_url, path=path, offset=offset)
                embedded = page.get("_embedded", {})
                embedded = embedded if isinstance(embedded, dict) else {}
                children = [
                    item for item in embedded.get("items", []) if isinstance(item, dict)
                ]
                for child in children:
                    child_path = str(child.get("path", ""))
                    if child.get("type") == "dir":
                        walk(child_path, depth + 1)
                    elif child.get("type") == "file":
                        try:
                            result.append(self._resource(public_url, path=child_path))
                        except FetchError:
                            result.append(child)
                total = embedded.get("total")
                if (
                    not children
                    or not isinstance(total, int)
                    or offset + len(children) >= total
                ):
                    return
                offset += len(children)

        walk(str(first.get("path", "/")))
        return result

    def _follow_short_link(self, url: str) -> str:
        response = self.client.request(url)
        candidates = [
            urljoin(history.url, history.headers["Location"])
            for history in response.history
            if history.headers.get("Location")
        ]
        candidates.append(response.url)
        for candidate in candidates:
            if self._is_public_url(candidate):
                return candidate
        match = re.search(
            r"(?:var|let|const)\s+redirectUrl\s*=\s*[\"']([^\"']+)[\"']",
            response.text,
            flags=re.IGNORECASE,
        )
        if match:
            return html.unescape(match.group(1)).replace("\\/", "/")
        raise FetchError(f"Public resource link was not found: {url}")

    def resolve(self, url: str) -> PublicFiles:
        if not url:
            return PublicFiles(url="", resolved_url="", status="missing")
        host = urlparse(url).netloc.lower().split(":", 1)[0]
        resolved = self._follow_short_link(url) if host in self.short_hosts else url
        if not self._is_public_url(resolved):
            name = Path(urlparse(resolved).path).name or "file"
            return PublicFiles(
                url=url,
                resolved_url=resolved,
                status="resolved",
                files=(PublicFile(name=name, path="", download_url=resolved),),
            )
        files = tuple(
            PublicFile(
                name=str(item.get("name") or Path(str(item.get("path", ""))).name),
                path=str(item.get("path", "")),
                download_url=str(item.get("file", "")),
                size=int(item["size"]) if isinstance(item.get("size"), int) else None,
                mime_type=str(item.get("mime_type") or item.get("media_type") or ""),
            )
            for item in self._files(resolved)
        )
        return PublicFiles(
            url=url,
            resolved_url=resolved,
            status="resolved" if files else "resolved_empty",
            files=files,
        )


__all__ = ["PublicFile", "PublicFileResolver", "PublicFiles"]
