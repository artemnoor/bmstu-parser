from __future__ import annotations

from pathlib import Path
from typing import Any

from ...core.capabilities import UniversityCapabilities
from ...core.config import load_plugin_config
from ...core.plugin import UniversityConfig, UniversityProviders
from ...core.source_models import SourceProgram
from ...domain.provenance import SourceProvenance

ROOT = Path(__file__).parent


class _BMSTUCapabilityProvider:
    """Placeholder source seam for capabilities materialized by the legacy
    composite pipeline.  It keeps the capability/provider contract explicit;
    the legacy runner below remains the source of the complete BMSTU result.
    """

    def __init__(self, capability: str) -> None:
        self.capability = capability

    def fetch(self) -> list[Any]:
        return []


class BmstuProgramsProvider:
    """Adapter around the proven BMSTU Mirror API implementation.

    Rate limiting, retries, worker balancing and per-item ordering remain in
    the existing HTTP/MirrorApi implementation.  This adapter only translates
    its result into a source DTO at the platform boundary.
    """

    capability = "programs"

    def __init__(self, *, workers: int = 6, page_size: int = 100) -> None:
        self.workers = workers
        self.page_size = page_size

    def fetch(self) -> list[SourceProgram]:
        from bmstu_parser.config import Settings
        from bmstu_parser.ingestion.http import ApiClient
        from bmstu_parser.ingestion.mirror_api import MirrorApi
        from bmstu_parser.transform.normalize import Normalizer

        settings = Settings(workers=self.workers, page_size=self.page_size)
        client = ApiClient(timeout=settings.timeout, delay=settings.delay)
        api = MirrorApi(client, workers=self.workers, page_size=self.page_size)
        summaries, _meta = api.fetch_major_list()
        details = api.fetch_details(summaries)
        majors = [Normalizer().normalize(item) for item in details]
        result: list[SourceProgram] = []
        for major in majors:
            for program in major.educational_programs:
                result.append(
                    SourceProgram(
                        source_key=program.code or program.id,
                        name=program.name,
                        code=program.code,
                        study_direction_key=major.slug or major.code,
                        department_key=program.department_id,
                        description=program.description,
                        study_plan_url=program.study_plan_url,
                        raw={"major_id": major.id, "program_id": program.id},
                        provenance=SourceProvenance(
                            source_page=major.provenance.source_page,
                            list_api=major.provenance.list_api,
                            detail_api=major.provenance.detail_api,
                            detail_page=major.provenance.detail_page,
                            fetched_at_utc=major.provenance.fetched_at_utc,
                            raw_snapshot_path=major.provenance.raw_snapshot_path,
                            source_key=program.id,
                        ),
                    )
                )
        return result


class BmstuPlugin:
    university_id = "bmstu"
    display_name = "МГТУ им. Н. Э. Баумана"

    def capabilities(self) -> UniversityCapabilities:
        config = load_plugin_config(ROOT / "config.yaml")
        return UniversityCapabilities(**config.capabilities)

    def providers(self) -> UniversityProviders:
        return UniversityProviders(
            programs=BmstuProgramsProvider(),
            curricula=_BMSTUCapabilityProvider("curricula"),
            faculties=_BMSTUCapabilityProvider("faculties"),
            departments=_BMSTUCapabilityProvider("departments"),
            admission=_BMSTUCapabilityProvider("admission"),
            tuition=_BMSTUCapabilityProvider("tuition"),
        )

    def resolver_names(self, field: str) -> tuple[str, ...]:
        config = load_plugin_config(ROOT / "config.yaml")
        return config.resolvers.get(field, ())

    def run_legacy(self, options: Any) -> dict[str, Any]:
        """Keep the battle-tested balanced BMSTU pipeline behind the plugin."""

        from bmstu_parser.config import Settings
        from bmstu_parser.pipeline import ScrapePipeline
        from bmstu_parser.transform.normalize import Normalizer

        quality = ScrapePipeline(
            Settings(
                output_dir=Path(options.output_dir) / self.university_id,
                workers=options.workers,
                page_size=options.page_size,
                timeout=options.timeout,
                delay=options.delay,
                resolve_plans=options.resolve_plans,
                download_plans=options.download_plans,
                strict=options.strict,
            )
        ).run()
        # Re-materialize the generic projection from the newly captured raw
        # snapshot. The source-specific balanced run remains authoritative for
        # ingestion; this adapter publishes the platform IDs afterwards.
        import json

        from ...migrations.bmstu import (
            BmstuRawReplayProvider,
            _global_aliases,
            _write_platform_projection,
        )

        output_dir = Path(options.output_dir) / self.university_id
        _, _, details = BmstuRawReplayProvider(output_dir).fetch()
        majors = [Normalizer().normalize(item) for item in details]
        _write_platform_projection(output_dir, majors)
        (output_dir / "id_aliases.json").write_text(
            json.dumps(
                {"schema_version": "2.0", "aliases": _global_aliases(majors)},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return quality

    def config(self) -> UniversityConfig:
        config = load_plugin_config(ROOT / "config.yaml")
        return UniversityConfig(
            university_id=config.university_id,
            display_name=config.display_name,
            config_path=ROOT / "config.yaml",
            settings=config.settings,
        )
