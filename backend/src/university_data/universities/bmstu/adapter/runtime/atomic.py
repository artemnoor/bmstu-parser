"""BMSTU adapter facade for the platform atomic writers."""

from university_data.runtime.atomic import (
    atomic_text_writer,
    atomic_write_csv,
    atomic_write_json,
    atomic_write_text,
)

__all__ = [
    "atomic_text_writer",
    "atomic_write_csv",
    "atomic_write_json",
    "atomic_write_text",
]
