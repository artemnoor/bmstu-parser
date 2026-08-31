# BMSTU backend

Python backend: ingestion, PDF/DOCX extraction, semantic curriculum
balancing, quality gates, ontology and FastAPI read/control API.

```powershell
cd backend
python -m pip install -e .
python -m pytest -q
ruff check src tests
ruff format --check src tests
python -m mypy src/bmstu_parser/domain src/bmstu_parser/api/repository.py src/bmstu_parser/api/job_store.py
python -m bmstu_parser api --result ../data/result --host 127.0.0.1 --port 8000
```

The backend is the only owner of `data/result`, source documents, parser
operations and balancing rules. The frontend does not import this package or
read parser files.

Production startup requires `BMSTU_ENV=production` and `BMSTU_API_KEY`.
Configure `BMSTU_CORS_ORIGINS` explicitly for direct cross-origin clients.

Dataset reads use DuckDB by default: CSV/JSONL remain the source of truth, but
pagination, counts, filters and search are executed by SQL without loading a
whole dataset into Python memory. Set `BMSTU_DATA_ENGINE=file` for the
portable row-by-row fallback. The active engine is returned by `/health` as
`data_engine`.

Operation status is persisted in
`data/result/pipeline_runs/operations.sqlite3`. The store recovers interrupted
`queued`/`running` operations after a restart, keeps one writer at a time and
applies bounded retention (TTL and maximum row count). It is still an
in-process single-worker control plane; a multi-instance deployment should
move this state to a shared queue/database.

Retention is configurable with `BMSTU_OPERATION_MAX_RECORDS` and
`BMSTU_OPERATION_TTL_SECONDS`.

Normalization is strict at the domain boundary: scores, counts and prices use
typed numeric values where parsing succeeds. The original value and a
`normalization_warnings` list are retained when it does not. Canonical IDs are
based on business keys and no longer depend on ordinary array order. Previous
IDs are written to `data/result/id_aliases.json`, and API lookups resolve those
aliases for compatibility.

Ontology objects and links keep the legacy scalar provenance fields plus a
`sources` list, so repeated observations from different API cards do not lose
lineage. The semantic curriculum implementation is split into geometry,
schema, curriculum parsing, reconciliation, quality, I/O and ontology modules;
the balancing rules remain in the backend and ambiguous source data is kept as
diagnostics instead of being silently rewritten.

For the complete API and dataset contract see `../docs/API.md`. The Docker
image installs Poppler (`pdftotext`) so the default native PDF reader works in
the container.

Export the backend OpenAPI contract from the repository root:

```powershell
python backend/scripts/export_openapi.py
```
