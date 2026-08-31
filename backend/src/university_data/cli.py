from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .migrations import migrate_bmstu
from .pipeline import PipelineOptions, UniversityPipeline
from .registry import REGISTRY


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="University Data Platform CLI")
    parser.add_argument("--output", type=Path, default=Path("data/result"))
    parser.add_argument("--university", default="bmstu", choices=REGISTRY.ids())
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument("--download-plans", action="store_true")
    parser.add_argument(
        "--no-resolve-plans", action="store_false", dest="resolve_plans", default=True
    )
    parser.add_argument("--strict", action="store_true")
    return parser


def build_migrate_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="university-data migrate")
    parser.add_argument("university", choices=("bmstu",))
    parser.add_argument("--from", dest="source", type=Path, required=True)
    parser.add_argument("--to", dest="target", type=Path, required=True)
    parser.add_argument(
        "--rebuild-derived", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--write-aliases", action=argparse.BooleanOptionalAction, default=True
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "migrate":
        args = build_migrate_parser().parse_args(raw[1:])
        report = migrate_bmstu(
            args.source,
            args.target,
            rebuild_derived=args.rebuild_derived,
            write_aliases=args.write_aliases,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    args = build_parser().parse_args(raw)
    options = PipelineOptions(
        output_dir=args.output,
        workers=args.workers,
        page_size=args.page_size,
        timeout=args.timeout,
        delay=args.delay,
        resolve_plans=args.resolve_plans,
        download_plans=args.download_plans,
        strict=args.strict,
    )
    report = UniversityPipeline(REGISTRY).run(args.university, options)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("verification", {}).get("passed") or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
