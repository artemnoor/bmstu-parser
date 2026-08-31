"""Temporary compatibility facade for the new platform namespace."""

from university_data import REGISTRY, UniversityRegistry
from university_data.pipeline import PipelineOptions, UniversityPipeline

__all__ = ["REGISTRY", "PipelineOptions", "UniversityPipeline", "UniversityRegistry"]
