"""Backward-compatible import for the BMSTU-owned migration."""

from ..universities.bmstu.migration import BmstuRawReplayProvider, migrate_bmstu

__all__ = ["BmstuRawReplayProvider", "migrate_bmstu"]
