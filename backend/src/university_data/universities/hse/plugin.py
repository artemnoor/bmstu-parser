from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ...core.capabilities import UniversityCapabilities
from ...core.config import ResolverSpec, load_plugin_config
from ...core.plugin import (
    ResolverRegistry,
    SourceProvider,
    UniversityConfig,
    UniversityManifest,
    UniversityOperations,
    UniversityProviders,
)
from .providers import HseProgramsProvider

ROOT = Path(__file__).parent


class _UnsupportedOperations:
    def execute(self, request: Any, result_dir: Path) -> dict[str, Any]:
        raise ValueError(f"HSE operation is not supported: {request.operation}")


class HsePlugin:
    university_id = "hse"
    display_name = "Национальный исследовательский университет «Высшая школа экономики»"

    def __init__(
        self,
        *,
        provider_overrides: Mapping[str, SourceProvider] | None = None,
        capabilities_override: UniversityCapabilities | None = None,
    ) -> None:
        self.provider_overrides = dict(provider_overrides or {})
        self.capabilities_override = capabilities_override

    def capabilities(self) -> UniversityCapabilities:
        if self.capabilities_override is not None:
            return self.capabilities_override
        config = load_plugin_config(ROOT / "manifest.yaml")
        return UniversityCapabilities(**config.capabilities)

    def manifest(self) -> UniversityManifest:
        config = load_plugin_config(ROOT / "manifest.yaml")
        return UniversityManifest(
            university_id=config.university_id,
            display_name=config.display_name,
            capabilities=self.capabilities().specs(allow_partial=config.allow_partial),
            module_version=config.module_version,
            config_path=ROOT / "manifest.yaml",
            settings=config.settings,
        )

    def providers(self, options: Any | None = None) -> UniversityProviders:
        if options is None:
            from ...pipeline import PipelineOptions

            options = PipelineOptions()
        providers: dict[str, SourceProvider] = {
            "programs": HseProgramsProvider(options)
        }
        providers.update(self.provider_overrides)
        return UniversityProviders(providers)

    def resolvers(self) -> ResolverRegistry:
        config = load_plugin_config(ROOT / "manifest.yaml")
        return ResolverRegistry(specs=config.resolvers)

    def config(self) -> UniversityConfig:
        config = load_plugin_config(ROOT / "manifest.yaml")
        return UniversityConfig(
            university_id=config.university_id,
            display_name=config.display_name,
            config_path=ROOT / "manifest.yaml",
            settings=config.settings,
        )

    def resolver_specs(self, field: str) -> tuple[ResolverSpec, ...]:
        config = load_plugin_config(ROOT / "manifest.yaml")
        return config.resolvers.get(field, ())

    def resolver_builders(
        self, field: str
    ) -> Mapping[str, Callable[[ResolverSpec], Any]]:
        return {}

    def operations(self) -> UniversityOperations:
        return _UnsupportedOperations()


__all__ = ["HsePlugin", "HseProgramsProvider"]
