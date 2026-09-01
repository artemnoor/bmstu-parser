"""Public HSE module facade for the platform registry."""

from .plugin import HsePlugin

HseModule = HsePlugin

__all__ = ["HseModule"]
