from __future__ import annotations

from dataclasses import dataclass

SITE_BASE = "https://mirror.bmstu.ru"
API_BASE = "https://api.mirror.bmstu.ru"
DEGREE = "baccalaureate-and-specialty"
SOURCE_PAGE = f"{SITE_BASE}/bachelor/majors"
LIST_ENDPOINT = f"{API_BASE}/majors/{DEGREE}"
DETAIL_ENDPOINT = f"{API_BASE}/majors/{{slug}}"
YANDEX_RESOURCE_ENDPOINT = "https://cloud-api.yandex.net/v1/disk/public/resources"
YANDEX_DOWNLOAD_ENDPOINT = (
    "https://cloud-api.yandex.net/v1/disk/public/resources/download"
)


@dataclass(frozen=True, slots=True)
class BmstuSourceConfig:
    site_base: str = SITE_BASE
    api_base: str = API_BASE
    list_endpoint: str = LIST_ENDPOINT
    detail_endpoint: str = DETAIL_ENDPOINT
    source_page: str = SOURCE_PAGE
