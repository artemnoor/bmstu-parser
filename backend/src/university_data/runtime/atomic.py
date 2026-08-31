from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TextIO, cast


@contextmanager
def atomic_text_writer(
    path: Path, *, encoding: str = "utf-8", newline: str | None = None
) -> Iterator[TextIO]:
    """Write an artifact to a sibling temporary file, then replace atomically."""

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
            yield cast(TextIO, stream)
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
        json.dumps(value, ensure_ascii=False, indent=indent, default=str),
    )


def atomic_write_csv(path: Path, writer_callback: Any) -> None:
    with atomic_text_writer(path, encoding="utf-8-sig", newline="") as stream:
        writer_callback(stream)
