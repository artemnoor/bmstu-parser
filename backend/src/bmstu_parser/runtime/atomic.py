from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, TextIO


@contextmanager
def atomic_text_writer(
    path: Path,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
) -> Iterator[TextIO]:
    """Write a text artifact through a sibling temporary file.

    This is an adapted, narrowed version of the atomic-write pattern from
    ``asagynbaev/pdf-extractor`` (MIT). The destination is replaced only
    after the writer closes successfully, so a failed run cannot leave a
    half-written dataset artifact behind.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline=newline,
            dir=path.parent,
            delete=False,
            suffix=".tmp",
        ) as stream:
            temporary_path = Path(stream.name)
            yield stream
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    with atomic_text_writer(path, encoding=encoding) as stream:
        stream.write(content)


def atomic_write_json(path: Path, value: Any, *, indent: int = 2) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=indent),
    )


def atomic_write_csv(
    path: Path,
    writer_callback: Any,
) -> None:
    """Run a CSV writer callback against a temporary destination."""

    with atomic_text_writer(path, encoding="utf-8-sig", newline="") as stream:
        writer_callback(stream)
