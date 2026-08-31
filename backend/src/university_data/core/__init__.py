"""University-neutral platform contracts and orchestration."""

from .capabilities import UniversityCapabilities
from .config import PluginConfig, load_plugin_config
from .plugin import UniversityConfig, UniversityPlugin, UniversityProviders
from .registry import REGISTRY, UniversityRegistry

__all__ = [
    "REGISTRY",
    "PluginConfig",
    "UniversityCapabilities",
    "UniversityConfig",
    "UniversityPlugin",
    "UniversityProviders",
    "UniversityRegistry",
    "load_plugin_config",
]
