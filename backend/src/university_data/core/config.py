from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .capabilities import CAPABILITY_NAMES


@dataclass(frozen=True, slots=True)
class PluginConfig:
    university_id: str
    display_name: str
    capabilities: dict[str, bool]
    resolvers: dict[str, tuple[str, ...]]
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
        isinstance(key, str)
        and isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        for key, value in resolvers.items()
    ):
        raise ValueError("resolvers must map fields to lists of hook names")
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
        resolvers={key: tuple(value) for key, value in resolvers.items()},
        settings=dict(settings),
    )
