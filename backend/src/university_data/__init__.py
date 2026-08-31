"""University Data Platform public package.

The package contains the university-neutral contracts and the registered
source adapters.  The historical ``bmstu_parser`` package remains available
as a compatibility facade while downstream consumers migrate.
"""

__version__ = "3.0.0"

from .core.registry import UniversityRegistry
from .registry import REGISTRY

__all__ = ["REGISTRY", "UniversityRegistry", "__version__"]
