from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


@dataclass(slots=True)
class Settings:
    output_dir: Path = Path("data/result")
    workers: int = 6
    page_size: int = 100
    timeout: float = 30.0
    delay: float = 0.15
    resolve_plans: bool = True
    download_plans: bool = False
    reader_backend: str = "native"
    resume_study_plans: bool = True
    strict: bool = False
    verbose: bool = False
