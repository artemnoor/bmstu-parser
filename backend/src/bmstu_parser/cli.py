from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import Settings
from .pipeline import ScrapePipeline
from .study_plans.compact import compact_existing_dataset
from .study_plans.pipeline import StudyPlanExtractionPipeline
from .study_plans.semantics import enrich_existing_dataset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Парсер программ обучения и учебных планов МГТУ им. Н. Э. Баумана."
    )
    parser.add_argument("--output", type=Path, default=Path("data/result"), help="Каталог результата")
    parser.add_argument("--workers", type=int, default=6, help="Число параллельных запросов карточек")
    parser.add_argument("--page-size", type=int, default=100, help="Размер страницы API")
    parser.add_argument("--timeout", type=float, default=30.0, help="Тайм-аут HTTP-запроса")
    parser.add_argument("--delay", type=float, default=0.15, help="Минимальная пауза между запросами")
    parser.add_argument(
        "--resolve-plans",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Разрешать ссылки учебных планов",
    )
    parser.add_argument("--download-plans", action="store_true", help="Скачивать найденные файлы планов")
    parser.add_argument("--strict", action="store_true", help="Завершать процесс с кодом 1 при провале quality gate")
    parser.add_argument("--verbose", action="store_true", help="Включить подробное логирование")
    return parser


def build_study_plan_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bmstu-parser extract-study-plans",
        description="Извлечь все таблицы из локальных учебных планов BMSTU.",
    )
    parser.add_argument("--result", type=Path, default=Path("data/result"), help="Каталог результата основного парсера")
    parser.add_argument("--workers", type=int, default=4, help="Число параллельных документов")
    parser.add_argument(
        "--reader-backend",
        choices=("native", "docling"),
        default="native",
        help="Backend извлечения PDF/DOCX; docling устанавливается через optional extra",
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Возобновлять обработку по checkpoints",
    )
    parser.add_argument("--strict", action="store_true", help="Завершать процесс с кодом 1 при провале quality gate")
    parser.add_argument("--verbose", action="store_true", help="Включить прогресс обработки")
    return parser


def run_study_plan_extraction(argv: list[str]) -> int:
    args = build_study_plan_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    quality = StudyPlanExtractionPipeline(
        args.result,
        workers=args.workers,
        reader_backend=args.reader_backend,
        resume=args.resume,
    ).run()
    print(json.dumps(quality, ensure_ascii=False, indent=2))
    return 0 if quality["verification"]["passed"] or not args.strict else 1


def run_study_plan_compaction(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="bmstu-parser compact-study-plans")
    parser.add_argument("--result", type=Path, default=Path("data/result"))
    args = parser.parse_args(argv)
    quality = compact_existing_dataset(args.result)
    print(json.dumps(quality, ensure_ascii=False, indent=2))
    return 0


def run_study_plan_semantics(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="bmstu-parser extract-study-plan-semantics")
    parser.add_argument("--result", type=Path, default=Path("data/result"))
    parser.add_argument("--strict", action="store_true", help="Завершать процесс с кодом 1 при провале semantic quality gate")
    args = parser.parse_args(argv)
    report = enrich_existing_dataset(args.result)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["verification"]["passed"] or not args.strict else 1


def run_api(argv: list[str]) -> int:
    from .api.cli import main as api_main

    return api_main(argv)


def main(argv: list[str] | None = None) -> int:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    if raw_args and raw_args[0] == "extract-study-plans":
        return run_study_plan_extraction(raw_args[1:])
    if raw_args and raw_args[0] == "compact-study-plans":
        return run_study_plan_compaction(raw_args[1:])
    if raw_args and raw_args[0] == "extract-study-plan-semantics":
        return run_study_plan_semantics(raw_args[1:])
    if raw_args and raw_args[0] == "api":
        return run_api(raw_args[1:])
    args = build_parser().parse_args(raw_args)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    settings = Settings(
        output_dir=args.output,
        workers=args.workers,
        page_size=args.page_size,
        timeout=args.timeout,
        delay=args.delay,
        resolve_plans=args.resolve_plans,
        download_plans=args.download_plans,
        strict=args.strict,
        verbose=args.verbose,
    )
    quality = ScrapePipeline(settings).run()
    print(json.dumps(quality, ensure_ascii=False, indent=2))
    return 0 if quality["verification"]["passed"] or not settings.strict else 1
