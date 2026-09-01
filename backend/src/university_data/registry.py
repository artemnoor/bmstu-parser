"""Application composition root for the statically registered adapters."""

from .core.registry import UniversityRegistry
from .universities.bmstu.module import BmstuModule
from .universities.fake.module import FakeModule
from .universities.hse.module import HseModule

REGISTRY = UniversityRegistry((BmstuModule(), FakeModule(), HseModule()))

__all__ = ["REGISTRY", "UniversityRegistry"]
