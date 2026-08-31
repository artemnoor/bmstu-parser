from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Runtime settings for the API process.

    The API key is optional for local development. Set ``BMSTU_API_KEY`` in
    a deployed environment to protect write operations.
    """

    result_dir: Path = Path("data/result")
    host: str = "127.0.0.1"
    port: int = 8000
    api_key: str = ""
    cors_origins: tuple[str, ...] = ()
    environment: str = "development"

    @property
    def is_production(self) -> bool:
        return self.environment.casefold() in {"production", "prod"}

    @classmethod
    def from_env(cls) -> "ApiSettings":
        configured_origins = os.getenv("BMSTU_CORS_ORIGINS")
        environment = os.getenv("BMSTU_ENV", "development")
        if (not configured_origins or not configured_origins.strip()) and environment.casefold() not in {
            "production",
            "prod",
        }:
            # The standalone local dashboard can be served by Python's static
            # server or opened directly as file:// (the browser origin is
            # then ``null``). Deployments should always set an explicit list.
            origins = (
                "http://127.0.0.1:5173",
                "http://localhost:5173",
                "null",
            )
        else:
            origins = tuple(
                origin.strip()
                for origin in configured_origins.split(",")
                if origin.strip()
            )
        return cls(
            result_dir=Path(os.getenv("BMSTU_RESULT_DIR", "data/result")),
            host=os.getenv("BMSTU_API_HOST", "127.0.0.1"),
            port=int(os.getenv("BMSTU_API_PORT", "8000")),
            api_key=os.getenv("BMSTU_API_KEY", ""),
            cors_origins=origins,
            environment=environment,
        )
