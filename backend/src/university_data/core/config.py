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
    allow_partial: set[str]
    resolvers: dict[str, tuple[ResolverSpec, ...]]
    settings: dict[str, Any]
    module_version: str


def load_plugin_config(path: Path) -> PluginConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Plugin config must be a mapping: {path}")
    allowed = {
        "university_id",
        "display_name",
        "capabilities",
        "resolvers",
        "settings",
        "module_version",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"Unknown plugin config keys: {sorted(unknown)}")
    capabilities = payload.get("capabilities", {})
    resolvers = payload.get("resolvers", {})
    settings = payload.get("settings", {})
    if not isinstance(capabilities, dict):
        raise TypeError("capabilities must be a mapping")
    unknown_capabilities = set(capabilities) - set(CAPABILITY_NAMES)
    if unknown_capabilities:
        raise ValueError(f"Unknown capabilities: {sorted(unknown_capabilities)}")
    normalized_capabilities: dict[str, bool] = {}
    allow_partial: set[str] = set()
    for key, value in capabilities.items():
        if isinstance(value, bool):
            normalized_capabilities[key] = value
            continue
        if not isinstance(value, dict) or not isinstance(value.get("enabled"), bool):
            raise TypeError(
                "capabilities values must be booleans or mappings with boolean 'enabled'"
            )
        unknown_options = set(value) - {"enabled", "allow_partial"}
        if unknown_options:
            raise ValueError(
                f"Unknown options for capability {key!r}: {sorted(unknown_options)}"
            )
        partial = value.get("allow_partial", False)
        if not isinstance(partial, bool):
            raise TypeError(f"Capability {key!r} allow_partial must be boolean")
        if partial and not value["enabled"]:
            raise ValueError(
                f"Capability {key!r} cannot allow partial data when disabled"
            )
        normalized_capabilities[key] = value["enabled"]
        if partial:
            allow_partial.add(key)
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
    module_version = str(payload.get("module_version", "0.1.0")).strip()
    if not university_id or not display_name:
        raise ValueError("university_id and display_name are required")
    if not module_version:
        raise ValueError("module_version must not be empty")
    return PluginConfig(
        university_id=university_id,
        display_name=display_name,
        capabilities=normalized_capabilities,
        allow_partial=allow_partial,
        resolvers=parsed_resolvers,
        settings=dict(settings),
        module_version=module_version,
    )
