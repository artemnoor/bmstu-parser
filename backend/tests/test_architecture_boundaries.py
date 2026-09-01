from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1] / "src" / "university_data"


def test_neutral_layers_do_not_import_university_specific_names() -> None:
    paths = [
        *((ROOT / "core").rglob("*.py")),
        ROOT / "pipeline.py",
        ROOT / "api" / "config.py",
        ROOT / "api" / "operations.py",
        ROOT / "cli.py",
    ]
    offenders = {
        str(path.relative_to(ROOT)): token
        for path in paths
        for token in ("bmstu", "hse")
        if token in path.read_text(encoding="utf-8").casefold()
    }
    assert offenders == {}
