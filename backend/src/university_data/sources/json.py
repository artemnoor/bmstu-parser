from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    """Read a source JSON payload without applying university semantics."""

    return json.loads(path.read_text(encoding="utf-8"))
