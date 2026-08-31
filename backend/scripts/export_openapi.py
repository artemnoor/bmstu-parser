from __future__ import annotations

import json
from pathlib import Path

from university_data.api.app import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = PROJECT_ROOT / "contracts" / "openapi.json"


def main() -> None:
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(CONTRACT_PATH)


if __name__ == "__main__":
    main()
