from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import LIST_ENDPOINT, Settings
from .ingestion.http import ApiClient
from .ingestion.mirror_api import MirrorApi
from .ingestion.yandex import StudyPlanResolver
from .outputs.writers import write_dataset
from .quality.checks import validate_dataset
from .runtime.lineage import PipelineRun
from .transform.normalize import Normalizer
from .transform.ontology import OntologyBuilder


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScrapePipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = ApiClient(timeout=settings.timeout, delay=settings.delay)
        self.api = MirrorApi(
            self.client,
            workers=settings.workers,
            page_size=settings.page_size,
        )
        self.normalizer = Normalizer()

    def run(self) -> dict[str, Any]:
        output_dir = Path(self.settings.output_dir)
        run = PipelineRun(output_dir, "scrape")
        try:
            fetched_at_utc = utc_now()
            summaries, list_meta = self.api.fetch_major_list()
            details = self.api.fetch_details(summaries)
            majors = [self.normalizer.normalize(item) for item in details]

            resolver = StudyPlanResolver(self.client, output_dir)
            resolver.enrich(
                majors,
                resolve=self.settings.resolve_plans,
                download=self.settings.download_plans,
            )

            ontology = OntologyBuilder().build(majors)
            quality = validate_dataset(summaries, list_meta, details, majors, ontology)
            write_dataset(
                output_dir,
                majors,
                ontology,
                quality,
                summaries,
                list_meta,
                details,
                fetched_at_utc,
            )
            run.stage(
                "ingest",
                inputs=[LIST_ENDPOINT],
                outputs=["raw/majors_list.json", "raw/details"],
                metadata={"list_items": len(summaries), "detail_items": len(details)},
            )
            run.stage(
                "canonical_transform",
                inputs=["raw/majors_list.json", "raw/details"],
                outputs=[
                    "bmstu_bachelor_majors.json",
                    "majors.csv",
                    "departments.csv",
                    "educational_programs.csv",
                    "entrance_subjects.csv",
                    "tuition.csv",
                    "disciplines.csv",
                    "historical_passing_scores.csv",
                    "study_plan_files.csv",
                ],
                metadata={"majors": len(majors)},
            )
            run.stage(
                "ontology_projection",
                inputs=["bmstu_bachelor_majors.json"],
                outputs=["ontology.json"],
                metadata={"objects": quality["counts"]["ontology_objects"], "links": quality["counts"]["ontology_links"]},
            )
            run.stage(
                "quality_gate",
                inputs=["raw/majors_list.json", "bmstu_bachelor_majors.json", "ontology.json"],
                outputs=["parse_report.json"],
                quality=quality,
            )
            run.finish(status="succeeded" if quality["verification"]["passed"] else "failed", quality=quality)
            return quality
        except Exception as exc:
            run.finish(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
