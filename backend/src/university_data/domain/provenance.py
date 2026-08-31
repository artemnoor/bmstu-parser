from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class FieldMeta:
    status: str
    method: str
    confidence: float
    sources: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SourceObservation:
    source_page: str = ""
    list_api: str = ""
    detail_api: str = ""
    detail_page: str = ""
    fetched_at_utc: str = ""
    raw_snapshot_path: str = ""
    source_key: str = ""


@dataclass(slots=True)
class SourceProvenance:
    source_page: str = ""
    list_api: str = ""
    detail_api: str = ""
    detail_page: str = ""
    fetched_at_utc: str = ""
    raw_snapshot_path: str = ""
    source_key: str = ""
    sources: list[SourceObservation] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.sources and any(
            getattr(self, name)
            for name in (
                "source_page",
                "list_api",
                "detail_api",
                "detail_page",
                "fetched_at_utc",
                "raw_snapshot_path",
                "source_key",
            )
        ):
            self.sources.append(
                SourceObservation(
                    source_page=self.source_page,
                    list_api=self.list_api,
                    detail_api=self.detail_api,
                    detail_page=self.detail_page,
                    fetched_at_utc=self.fetched_at_utc,
                    raw_snapshot_path=self.raw_snapshot_path,
                    source_key=self.source_key,
                )
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
