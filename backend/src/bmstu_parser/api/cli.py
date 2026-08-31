from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from .app import create_app
from .config import ApiSettings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HTTP API для BMSTU education parser")
    env = ApiSettings.from_env()
    parser.add_argument("--result", type=Path, default=env.result_dir, help="Каталог результатов parser")
    parser.add_argument("--host", default=env.host, help="Адрес bind")
    parser.add_argument("--port", type=int, default=env.port, help="Порт HTTP API")
    parser.add_argument("--api-key", default=None, help="API key для write endpoints; по умолчанию BMSTU_API_KEY")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = replace(
        ApiSettings.from_env(),
        result_dir=args.result,
        host=args.host,
        port=args.port,
        api_key=ApiSettings.from_env().api_key if args.api_key is None else args.api_key,
    )
    import uvicorn

    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    return 0
