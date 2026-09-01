from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ApiSettings:
    result_dir: Path = Path("data/result")
    host: str = "127.0.0.1"
    port: int = 8000
    api_key: str = ""
    cors_origins: tuple[str, ...] = ()
    environment: str = "development"
    operation_max_records: int = 1000
    operation_ttl_seconds: int = 30 * 24 * 60 * 60
    operation_workers: int = 4

    @property
    def is_production(self) -> bool:
        return self.environment.casefold() in {"production", "prod"}

    @classmethod
    def from_env(cls) -> ApiSettings:
        environment = os.getenv("UNIVERSITY_ENV", "development")
        configured = os.getenv("UNIVERSITY_CORS_ORIGINS", "")
        if configured.strip():
            origins = tuple(
                item.strip() for item in configured.split(",") if item.strip()
            )
        elif not environment.casefold() in {"production", "prod"}:
            origins = ("http://127.0.0.1:5173", "http://localhost:5173", "null")
        else:
            origins = ()
        return cls(
            result_dir=Path(os.getenv("UNIVERSITY_RESULT_DIR", "data/result")),
            host=os.getenv("UNIVERSITY_API_HOST", "127.0.0.1"),
            port=int(os.getenv("UNIVERSITY_API_PORT", "8000")),
            api_key=os.getenv("UNIVERSITY_API_KEY", ""),
            cors_origins=origins,
            environment=environment,
            operation_max_records=max(
                1, int(os.getenv("UNIVERSITY_OPERATION_MAX_RECORDS", "1000"))
            ),
            operation_ttl_seconds=max(
                1,
                int(
                    os.getenv(
                        "UNIVERSITY_OPERATION_TTL_SECONDS", str(30 * 24 * 60 * 60)
                    )
                ),
            ),
            operation_workers=max(
                1, min(32, int(os.getenv("UNIVERSITY_OPERATION_WORKERS", "4")))
            ),
        )
