from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Literal, Protocol, TypeVar

ResolutionStatus = Literal[
    "published", "derived", "not_published", "ambiguous", "invalid"
]
T = TypeVar("T")


@dataclass(slots=True)
class Resolution(Generic[T]):
    value: T | None
    status: ResolutionStatus
    method: str
    confidence: float
    sources: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.value is not None and self.status in {"published", "derived"}


class Resolver(Protocol[T]):
    name: str

    def resolve(self, source: dict[str, Any]) -> Resolution[T]: ...


class DirectValueResolver:
    name = "direct"

    def __init__(self, field: str = "total_hours") -> None:
        self.field = field

    def resolve(self, source: dict[str, Any]) -> Resolution[int | float]:
        value = source.get(self.field)
        if value in (None, ""):
            return Resolution(None, "not_published", self.name, 0.0)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return Resolution(
                None,
                "invalid",
                self.name,
                0.0,
                warnings=[f"{self.field} is not numeric"],
            )
        return Resolution(value, "published", self.name, 1.0)


class SumHourComponentsResolver:
    name = "sum_components"

    def __init__(self, field: str = "components") -> None:
        self.field = field

    def resolve(self, source: dict[str, Any]) -> Resolution[int | float]:
        components = source.get(self.field)
        if not isinstance(components, dict) or not components:
            return Resolution(None, "not_published", self.name, 0.0)
        values = [
            value
            for value in components.values()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        if len(values) != len(components):
            return Resolution(
                None,
                "invalid",
                self.name,
                0.0,
                warnings=["hour components contain non-numeric values"],
            )
        return Resolution(sum(values), "derived", self.name, 1.0)


class CreditsToHoursResolver:
    name = "credits_to_hours"

    def __init__(self, hours_per_credit: float = 36) -> None:
        self.hours_per_credit = hours_per_credit

    def resolve(self, source: dict[str, Any]) -> Resolution[int | float]:
        credits = source.get("credits")
        if credits in (None, ""):
            return Resolution(None, "not_published", self.name, 0.0)
        if isinstance(credits, bool) or not isinstance(credits, (int, float)):
            return Resolution(
                None, "invalid", self.name, 0.0, warnings=["credits is not numeric"]
            )
        return Resolution(
            credits * self.hours_per_credit,
            "derived",
            self.name,
            0.7,
            warnings=["hours derived from credits"],
        )


class ResolverChain(Generic[T]):
    def __init__(self, resolvers: list[Resolver[T]]) -> None:
        self.resolvers = list(resolvers)

    def resolve(self, source: dict[str, Any]) -> Resolution[T]:
        last: Resolution[T] = Resolution(None, "not_published", "chain", 0.0)
        for resolver in self.resolvers:
            result = resolver.resolve(source)
            last = result
            if result.resolved:
                return result
            if result.status == "ambiguous":
                return result
        return last
