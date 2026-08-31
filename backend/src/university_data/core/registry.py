from __future__ import annotations

from collections.abc import Iterable, Iterator

from .plugin import UniversityPlugin


class UniversityNotFoundError(LookupError):
    pass


class UniversityRegistry:
    """Small explicit registry; plugin discovery is intentionally avoided."""

    def __init__(self, plugins: Iterable[UniversityPlugin] = ()) -> None:
        self._plugins: dict[str, UniversityPlugin] = {}
        for plugin in plugins:
            identifier = str(plugin.university_id).strip().casefold()
            if not identifier or identifier in self._plugins:
                raise ValueError(f"Duplicate or empty university_id: {identifier!r}")
            self._plugins[identifier] = plugin

    def get(self, university_id: str) -> UniversityPlugin | None:
        return self._plugins.get(str(university_id).strip().casefold())

    def require(self, university_id: str) -> UniversityPlugin:
        plugin = self.get(university_id)
        if plugin is None:
            raise UniversityNotFoundError(
                f"University is not registered: {university_id}"
            )
        return plugin

    def __iter__(self) -> Iterator[UniversityPlugin]:
        return iter(self._plugins.values())

    def ids(self) -> tuple[str, ...]:
        return tuple(self._plugins)


# Composition is kept outside ``core`` so the neutral layer never imports a
# concrete university adapter.  Applications use ``university_data.REGISTRY``.
REGISTRY = UniversityRegistry()
