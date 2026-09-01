"""University-neutral platform contracts and orchestration."""

from .capabilities import UniversityCapabilities
from .config import PluginConfig, ResolverSpec, load_plugin_config
from .contracts import (
    EXPECTED_SOURCE_TYPES,
    ProviderContractError,
    validate_provider_output,
)
from .plugin import (
    UniversityConfig,
    UniversityOperations,
    UniversityPlugin,
    UniversityProviders,
)
from .registry import REGISTRY, UniversityRegistry

__all__ = [
    "EXPECTED_SOURCE_TYPES",
    "REGISTRY",
    "PluginConfig",
    "ProviderContractError",
    "ResolverSpec",
    "UniversityCapabilities",
    "UniversityConfig",
    "UniversityOperations",
    "UniversityPlugin",
    "UniversityProviders",
    "UniversityRegistry",
    "load_plugin_config",
    "validate_provider_output",
]
