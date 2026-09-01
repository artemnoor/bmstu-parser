from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit


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


def provenance_source_key(value: SourceProvenance | dict[str, Any]) -> str:
    if isinstance(value, SourceProvenance):
        source_key = value.source_key
        observations: Any = value.sources
    else:
        source_key = str(value.get("source_key", ""))
        observations = value.get("sources", [])
    if source_key.strip():
        return source_key.strip()
    if isinstance(observations, list):
        for observation in observations:
            if isinstance(observation, SourceObservation):
                candidate = observation.source_key
            elif isinstance(observation, dict):
                candidate = str(observation.get("source_key", ""))
            else:
                candidate = ""
            if candidate.strip():
                return candidate.strip()
    return ""


def _observations(value: SourceProvenance | dict[str, Any]) -> list[Any]:
    if isinstance(value, SourceProvenance):
        return [value, *value.sources]
    observations = value.get("sources", [])
    return [value, *(observations if isinstance(observations, list) else [])]


def _locator(value: Any) -> bool:
    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme.casefold() in {"http", "https"}:
        return bool(parsed.netloc and parsed.path is not None)
    if parsed.scheme.casefold() == "file":
        return bool(parsed.netloc or parsed.path)
    return False


def provenance_has_source_locator(value: SourceProvenance | dict[str, Any]) -> bool:
    fields = ("source_page", "list_api", "detail_api", "detail_page")
    return any(
        _locator(
            item.get(field, "") if isinstance(item, dict) else getattr(item, field, "")
        )
        for item in _observations(value)
        for field in fields
    )


def provenance_has_lineage(value: SourceProvenance | dict[str, Any]) -> bool:
    return any(
        bool(
            item.get("raw_snapshot_path", "")
            if isinstance(item, dict)
            else getattr(item, "raw_snapshot_path", "")
        )
        for item in _observations(value)
    )


__all__ = [
    "FieldMeta",
    "SourceObservation",
    "SourceProvenance",
    "provenance_has_lineage",
    "provenance_has_source_locator",
    "provenance_source_key",
]
