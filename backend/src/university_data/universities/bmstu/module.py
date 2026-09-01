"""Public BMSTU module facade for the platform registry."""

from .plugin import BmstuPlugin

BmstuModule = BmstuPlugin

__all__ = ["BmstuModule"]
