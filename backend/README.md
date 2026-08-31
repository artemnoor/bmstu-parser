# BMSTU backend

Python backend: ingestion, PDF/DOCX extraction, semantic curriculum
balancing, quality gates, ontology and FastAPI read/control API.

```powershell
cd backend
python -m pip install -e .
python -m pytest -q
ruff check src tests
python -m bmstu_parser api --result ../data/result --host 127.0.0.1 --port 8000
```

The backend is the only owner of `data/result`, source documents, parser
operations and balancing rules. The frontend does not import this package or
read parser files.

Production startup requires `BMSTU_ENV=production` and `BMSTU_API_KEY`.
Configure `BMSTU_CORS_ORIGINS` explicitly for direct cross-origin clients.

Export the backend OpenAPI contract from the repository root:

```powershell
python backend/scripts/export_openapi.py
```
