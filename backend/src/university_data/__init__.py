"""University Data Platform public package.

The package contains the university-neutral contracts and the registered
source adapters.
"""

__version__ = "3.0.0"

from .core.registry import UniversityRegistry
from .registry import REGISTRY

__all__ = ["REGISTRY", "UniversityRegistry", "__version__"]
