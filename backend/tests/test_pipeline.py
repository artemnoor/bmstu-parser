import json
from pathlib import Path

from bmstu_parser.config import Settings
from bmstu_parser.ingestion.mirror_api import DetailFetch
from bmstu_parser.pipeline import ScrapePipeline


class _FakeMirrorApi:
    def __init__(self, summary: dict[str, str]) -> None:
        self.summary = summary

    def fetch_major_list(self) -> tuple[list[dict[str, str]], dict[str, int]]:
        return [self.summary], {"count": 1}

    def fetch_details(self, summaries: list[dict[str, str]]) -> list[DetailFetch]:
        return [
            DetailFetch(
                summary,
                {"additional": {"name": "Example major", "code": "01.01.01"}},
                None,
                "now",
            )
            for summary in summaries
        ]


def test_scrape_pipeline_records_stage_lineage(tmp_path: Path) -> None:
    summary = {"slug": "example-010101", "name": "Example major", "code": "01.01.01"}
    pipeline = ScrapePipeline(
        Settings(output_dir=tmp_path, resolve_plans=False, download_plans=False),
        api=_FakeMirrorApi(summary),
    )

    quality = pipeline.run()

    assert quality["verification"]["passed"] is True
    manifests = [
        path
        for path in (tmp_path / "pipeline_runs").glob("*.json")
        if path.name != "latest.json"
    ]
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["pipeline"] == "scrape"
    assert manifest["status"] == "succeeded"
    assert [stage["name"] for stage in manifest["stages"]] == [
        "ingest",
        "canonical_transform",
        "ontology_projection",
        "quality_gate",
    ]
