"""Application composition root for the statically registered adapters."""

from .core.registry import UniversityRegistry
from .universities.bmstu.plugin import BmstuPlugin
from .universities.fake.plugin import FakeUniversityPlugin

REGISTRY = UniversityRegistry((BmstuPlugin(), FakeUniversityPlugin()))

__all__ = ["REGISTRY", "UniversityRegistry"]
