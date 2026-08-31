from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .app import create_app
from .config import ApiSettings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="University Data Platform API")
    env = ApiSettings.from_env()
    parser.add_argument("--result", type=str, default=str(env.result_dir))
    parser.add_argument("--host", default=env.host)
    parser.add_argument("--port", type=int, default=env.port)
    args = parser.parse_args(argv)
    settings = ApiSettings(
        result_dir=Path(args.result),
        host=args.host,
        port=args.port,
        api_key=env.api_key,
        cors_origins=env.cors_origins,
        environment=env.environment,
    )
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    return 0
