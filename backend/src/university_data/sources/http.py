"""Provider-neutral resilient HTTP client.

The implementation is kept behind this import seam during the migration so
the existing retry, rate-limit, per-thread session and atomic-download rules
continue to be exercised unchanged.
"""

from bmstu_parser.ingestion.http import ApiClient, FetchError, RateLimiter

__all__ = ["ApiClient", "FetchError", "RateLimiter"]
