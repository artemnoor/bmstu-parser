from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

from .capabilities import CAPABILITY_NAMES, CapabilitySpec, UniversityCapabilities
from .config import ResolverSpec, load_plugin_config

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class UniversityConfig:
    """Validated runtime configuration exposed by a university adapter."""

    university_id: str
    display_name: str
    config_path: Path | None = None
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DataGap:
    """A non-fatal, source-owned explanation for a partial provider result."""

    code: str
    message: str
    source_key: str = ""


@dataclass(frozen=True, slots=True)
class ProviderResult(Generic[T]):
    """Validated source records plus explicit completeness information."""

    records: tuple[T, ...]
    complete: bool = True
    warnings: tuple[str, ...] = ()
    gaps: tuple[DataGap, ...] = ()


class ResolverRegistry:
    """University-owned resolver declarations and builder implementations."""

    def __init__(
        self,
        specs: Mapping[str, tuple[ResolverSpec, ...]] | None = None,
        builders: Mapping[str, Mapping[str, Callable[[ResolverSpec], Any]]]
        | None = None,
    ) -> None:
        self._specs = dict(specs or {})
        self._builders = {
            field: dict(field_builders)
            for field, field_builders in (builders or {}).items()
        }

    def specs_for(self, field: str) -> tuple[ResolverSpec, ...]:
        return self._specs.get(field, ())

    def builders_for(self, field: str) -> Mapping[str, Callable[[ResolverSpec], Any]]:
        return self._builders.get(field, {})


@dataclass(frozen=True, slots=True)
class UniversityManifest:
    """Small, cacheable public contract of a university module."""

    university_id: str
    display_name: str
    capabilities: tuple[CapabilitySpec, ...]
    module_version: str = "0.1.0"
    config_path: Path | None = None
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.university_id.strip() or not self.display_name.strip():
            raise ValueError("University manifest requires an id and display name")
        if not self.module_version.strip():
            raise ValueError("University manifest requires a module version")
        if not all(isinstance(item, CapabilitySpec) for item in self.capabilities):
            raise TypeError("University manifest capabilities must be CapabilitySpec")
        names = [item.name for item in self.capabilities]
        if len(names) != len(set(names)):
            raise ValueError("University manifest contains duplicate capabilities")

    def capability(self, name: str) -> CapabilitySpec:
        for item in self.capabilities:
            if item.name == name:
                return item
        if name not in CAPABILITY_NAMES:
            raise ValueError(f"Unknown university capability: {name}")
        return CapabilitySpec(name=name)

    def capability_specs(self) -> tuple[CapabilitySpec, ...]:
        return tuple(self.capability(name) for name in CAPABILITY_NAMES)

    def capabilities_dict(self) -> dict[str, bool]:
        return {item.name: item.enabled for item in self.capability_specs()}

    def config_hash(self) -> str:
        if self.config_path is not None and self.config_path.is_file():
            payload = self.config_path.read_bytes()
        else:
            payload = json.dumps(
                {
                    "university_id": self.university_id,
                    "capabilities": self.capabilities_dict(),
                    "settings": dict(self.settings),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@runtime_checkable
class SourceProvider(Protocol):
    capability: str
    persists_raw: bool

    def fetch(self) -> list[Any] | ProviderResult[Any]: ...


@runtime_checkable
class UniversityOperations(Protocol):
    """University-specific long-running operations behind a plugin seam."""

    def execute(self, request: Any, result_dir: Path) -> dict[str, Any]: ...


class ProviderSet(Mapping[str, SourceProvider]):
    """Open mapping of the fixed core capabilities to source providers."""

    def __init__(
        self,
        providers: Mapping[str, SourceProvider] | None = None,
        **named_providers: SourceProvider | None,
    ) -> None:
        values = dict(providers or {})
        values.update(
            {
                name: provider
                for name, provider in named_providers.items()
                if provider is not None
            }
        )
        unknown = set(values) - set(CAPABILITY_NAMES)
        if unknown:
            raise ValueError(f"Unknown provider capabilities: {sorted(unknown)}")
        self._providers = values

    def __getitem__(self, key: str) -> SourceProvider:
        return self._providers[key]

    def __iter__(self):
        return iter(self._providers)

    def __len__(self) -> int:
        return len(self._providers)

    def for_capability(self, capability: str) -> SourceProvider | None:
        return self._providers.get(capability)


class UniversityProviders(ProviderSet):
    """Compatibility name for existing plugins; it is no longer fixed-field."""


@runtime_checkable
class UniversityPlugin(Protocol):
    university_id: str
    display_name: str

    def capabilities(self) -> UniversityCapabilities: ...

    def providers(self, options: Any | None = None) -> ProviderSet: ...

    def config(self) -> UniversityConfig: ...

    def resolver_specs(self, field: str) -> tuple[ResolverSpec, ...]: ...

    def resolver_builders(
        self, field: str
    ) -> Mapping[str, Callable[[ResolverSpec], Any]]: ...

    def operations(self) -> UniversityOperations: ...


@runtime_checkable
class UniversityModule(Protocol):
    """Preferred contract for new university adapters."""

    def manifest(self) -> UniversityManifest: ...

    def providers(self, options: Any | None = None) -> ProviderSet: ...

    def resolvers(self) -> ResolverRegistry: ...

    def operations(self) -> UniversityOperations: ...


class UnsupportedUniversityOperations:
    """Default operations object for modules without custom operations."""

    def execute(self, request: Any, result_dir: Path) -> dict[str, Any]:
        operation = getattr(request, "operation", "unknown")
        raise ValueError(f"University operation is not supported: {operation}")


def resolver_specs_for(plugin: Any, field: str) -> tuple[ResolverSpec, ...]:
    # Keep subclasses of the compatibility facade overridable while allowing a
    # new module to expose only ResolverRegistry.
    resolver_specs = getattr(plugin, "resolver_specs", None)
    if callable(resolver_specs):
        return resolver_specs(field)
    registry_method = getattr(plugin, "resolvers", None)
    if callable(registry_method):
        registry = registry_method()
        if isinstance(registry, ResolverRegistry):
            return registry.specs_for(field)
    return ()


def resolver_builders_for(
    plugin: Any, field: str
) -> Mapping[str, Callable[[ResolverSpec], Any]]:
    resolver_builders = getattr(plugin, "resolver_builders", None)
    if callable(resolver_builders):
        return resolver_builders(field)
    registry_method = getattr(plugin, "resolvers", None)
    if callable(registry_method):
        registry = registry_method()
        if isinstance(registry, ResolverRegistry):
            return registry.builders_for(field)
    return {}


def manifest_for_plugin(plugin: Any) -> UniversityManifest:
    """Read the new manifest or adapt the legacy plugin contract."""

    manifest = getattr(plugin, "manifest", None)
    if callable(manifest):
        value = manifest()
        if not isinstance(value, UniversityManifest):
            raise TypeError("plugin.manifest() must return UniversityManifest")
        return value

    capabilities = plugin.capabilities()
    config_method = getattr(plugin, "config", None)
    config = config_method() if callable(config_method) else None
    if config is None:
        return UniversityManifest(
            university_id=str(plugin.university_id),
            display_name=str(plugin.display_name),
            capabilities=capabilities.specs(),
        )
    return UniversityManifest(
        university_id=config.university_id,
        display_name=config.display_name,
        capabilities=capabilities.specs(
            allow_partial=set(getattr(config, "allow_partial", set()))
        ),
        module_version=str(getattr(config, "module_version", "0.1.0")),
        config_path=config.config_path,
        settings=config.settings,
    )


def load_manifest(path: Path) -> UniversityManifest:
    """Build a module manifest from its YAML declaration."""

    config = load_plugin_config(path)
    return UniversityManifest(
        university_id=config.university_id,
        display_name=config.display_name,
        capabilities=UniversityCapabilities(**config.capabilities).specs(
            allow_partial=config.allow_partial
        ),
        module_version=config.module_version,
        config_path=path,
        settings=config.settings,
    )


__all__ = [
    "DataGap",
    "ProviderResult",
    "ProviderSet",
    "ResolverRegistry",
    "SourceProvider",
    "UniversityConfig",
    "UniversityManifest",
    "UniversityModule",
    "UniversityOperations",
    "UniversityPlugin",
    "UniversityProviders",
    "UnsupportedUniversityOperations",
    "load_manifest",
    "manifest_for_plugin",
    "resolver_builders_for",
    "resolver_specs_for",
]
