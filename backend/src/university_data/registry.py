"""Application composition root for the statically registered adapters."""

from .core.registry import UniversityRegistry
from .universities.bmstu.plugin import BmstuPlugin
from .universities.fake.plugin import FakeUniversityPlugin
from .universities.hse.plugin import HsePlugin

REGISTRY = UniversityRegistry((BmstuPlugin(), FakeUniversityPlugin(), HsePlugin()))

__all__ = ["REGISTRY", "UniversityRegistry"]
