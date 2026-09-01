"""University-neutral platform contracts and orchestration."""

from .capabilities import (
    CapabilityDefinition,
    CapabilitySpec,
    CapabilityStatus,
    UniversityCapabilities,
    capability_specs,
)
from .capability_registry import CORE_CAPABILITY_DEFINITIONS, RELATION_CAPABILITIES
from .config import PluginConfig, ResolverSpec, load_plugin_config
from .contracts import (
    EXPECTED_SOURCE_TYPES,
    ProviderContractError,
    validate_provider_output,
    validate_provider_result,
)
from .plugin import (
    DataGap,
    ProviderResult,
    ProviderSet,
    ResolverRegistry,
    UniversityConfig,
    UniversityManifest,
    UniversityModule,
    UniversityOperations,
    UniversityPlugin,
    UniversityProviders,
    UnsupportedUniversityOperations,
    load_manifest,
    manifest_for_plugin,
    resolver_builders_for,
    resolver_specs_for,
)
from .registry import REGISTRY, UniversityRegistry

__all__ = [
    "CORE_CAPABILITY_DEFINITIONS",
    "EXPECTED_SOURCE_TYPES",
    "REGISTRY",
    "RELATION_CAPABILITIES",
    "CapabilityDefinition",
    "CapabilitySpec",
    "CapabilityStatus",
    "DataGap",
    "PluginConfig",
    "ProviderContractError",
    "ProviderResult",
    "ProviderSet",
    "ResolverRegistry",
    "ResolverSpec",
    "UniversityCapabilities",
    "UniversityConfig",
    "UniversityManifest",
    "UniversityModule",
    "UniversityOperations",
    "UniversityPlugin",
    "UniversityProviders",
    "UniversityRegistry",
    "UnsupportedUniversityOperations",
    "capability_specs",
    "load_manifest",
    "load_plugin_config",
    "manifest_for_plugin",
    "resolver_builders_for",
    "resolver_specs_for",
    "validate_provider_output",
    "validate_provider_result",
]
