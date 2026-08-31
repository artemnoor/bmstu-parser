from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .capabilities import CAPABILITY_NAMES


@dataclass(frozen=True, slots=True)
class ResolverSpec:
    """A typed resolver declaration loaded from a plugin YAML file."""

    type: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PluginConfig:
    university_id: str
    display_name: str
    capabilities: dict[str, bool]
    resolvers: dict[str, tuple[ResolverSpec, ...]]
    settings: dict[str, Any]


def load_plugin_config(path: Path) -> PluginConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Plugin config must be a mapping: {path}")
    allowed = {"university_id", "display_name", "capabilities", "resolvers", "settings"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"Unknown plugin config keys: {sorted(unknown)}")
    capabilities = payload.get("capabilities", {})
    resolvers = payload.get("resolvers", {})
    settings = payload.get("settings", {})
    if not isinstance(capabilities, dict) or not all(
        isinstance(key, str) and isinstance(value, bool)
        for key, value in capabilities.items()
    ):
        raise ValueError("capabilities must be a mapping of strings to booleans")
    unknown_capabilities = set(capabilities) - set(CAPABILITY_NAMES)
    if unknown_capabilities:
        raise ValueError(f"Unknown capabilities: {sorted(unknown_capabilities)}")
    if not isinstance(resolvers, dict) or not all(
        isinstance(key, str) and isinstance(value, list)
        for key, value in resolvers.items()
    ):
        raise ValueError("resolvers must map fields to lists of typed specs")
    parsed_resolvers: dict[str, tuple[ResolverSpec, ...]] = {}
    for field_name, values in resolvers.items():
        specs: list[ResolverSpec] = []
        for value in values:
            if isinstance(value, str):
                specs.append(ResolverSpec(type=value))
                continue
            if not isinstance(value, dict) or not isinstance(value.get("type"), str):
                raise TypeError(f"resolver {field_name!r} must contain a string 'type'")
            parameters = {
                str(key): item for key, item in value.items() if key != "type"
            }
            specs.append(ResolverSpec(type=str(value["type"]), parameters=parameters))
        parsed_resolvers[field_name] = tuple(specs)
    if not isinstance(settings, dict):
        raise TypeError("settings must be a mapping")
    university_id = str(payload.get("university_id", "")).strip()
    display_name = str(payload.get("display_name", "")).strip()
    if not university_id or not display_name:
        raise ValueError("university_id and display_name are required")
    return PluginConfig(
        university_id=university_id,
        display_name=display_name,
        capabilities=dict(capabilities),
        resolvers=parsed_resolvers,
        settings=dict(settings),
    )
