"""Public fixture module facade for the platform registry."""

from .plugin import FakeUniversityPlugin

FakeModule = FakeUniversityPlugin

__all__ = ["FakeModule"]
