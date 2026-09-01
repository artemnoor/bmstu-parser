from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from .api.models import OperationName, OperationRequest
from .pipeline import PipelineOptions, UniversityPipeline
from .registry import REGISTRY


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="University Data Platform CLI")
    parser.add_argument("--output", type=Path, default=Path("data/result"))
    parser.add_argument("--university", required=True, choices=REGISTRY.ids())
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument(
        "--reader-backend", choices=("native", "docling"), default="native"
    )
    parser.add_argument("--download-plans", action="store_true")
    parser.add_argument(
        "--no-resolve-plans", action="store_false", dest="resolve_plans", default=True
    )
    parser.add_argument("--strict", action="store_true")
    return parser


def build_migrate_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="university-data migrate")
    parser.add_argument("university", choices=REGISTRY.ids())
    parser.add_argument("--from", dest="source", type=Path, required=True)
    parser.add_argument("--to", dest="target", type=Path, required=True)
    parser.add_argument(
        "--rebuild-derived", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--write-aliases", action=argparse.BooleanOptionalAction, default=True
    )
    return parser


def build_operation_parser(operation: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"university-data {operation}")
    parser.add_argument("--university", required=True, choices=REGISTRY.ids())
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--reader-backend", choices=("native", "docling"), default="native"
    )
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser


def run_module_operation(operation: str, argv: list[str]) -> int:
    args = build_operation_parser(operation).parse_args(argv)
    request = OperationRequest(
        operation=cast(OperationName, operation),
        workers=args.workers,
        reader_backend=args.reader_backend,
        strict=args.strict,
        resume=not args.no_resume,
    )
    plugin = REGISTRY.require(args.university)
    result = plugin.operations().execute(request, args.result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    passed = result.get("verification", {}).get("passed", True)
    return 0 if passed or not args.strict else 1


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "migrate":
        args = build_migrate_parser().parse_args(raw[1:])
        plugin = REGISTRY.require(args.university)
        migrator = getattr(plugin, "migrate", None)
        if not callable(migrator):
            raise ValueError(
                f"University module {args.university!r} does not expose migration"
            )
        report = migrator(
            args.source,
            args.target,
            rebuild_derived=args.rebuild_derived,
            write_aliases=args.write_aliases,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if raw and raw[0] in {
        "extract_study_plans",
        "extract_semantics",
        "compact_study_plans",
    }:
        return run_module_operation(raw[0], raw[1:])
    args = build_parser().parse_args(raw)
    options = PipelineOptions(
        output_dir=args.output,
        workers=args.workers,
        page_size=args.page_size,
        timeout=args.timeout,
        delay=args.delay,
        resolve_plans=args.resolve_plans,
        download_plans=args.download_plans,
        reader_backend=args.reader_backend,
        strict=args.strict,
    )
    report = UniversityPipeline(REGISTRY).run(args.university, options)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("verification", {}).get("passed") or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
