"""University-neutral platform contracts and orchestration."""

from .capabilities import UniversityCapabilities
from .config import PluginConfig, ResolverSpec, load_plugin_config
from .plugin import (
    UniversityConfig,
    UniversityOperations,
    UniversityPlugin,
    UniversityProviders,
)
from .registry import REGISTRY, UniversityRegistry

__all__ = [
    "REGISTRY",
    "PluginConfig",
    "ResolverSpec",
    "UniversityCapabilities",
    "UniversityConfig",
    "UniversityOperations",
    "UniversityPlugin",
    "UniversityProviders",
    "UniversityRegistry",
    "load_plugin_config",
]
