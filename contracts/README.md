# API contracts

`openapi.json` is generated from the parser backend FastAPI application and is
the contract for its external consumers. Regenerate it after changing routes
or Pydantic models:

```powershell
python backend/scripts/export_openapi.py
```

The contract contains no secrets. Domain balancing remains implemented only in
the backend semantic layer; the independent frontend consumes its projections.

The contract includes the active dataset engine in `GET /health.data_engine`
(`duckdb` by default, `file` fallback) and the durable operation schemas. Keep
this file regenerated whenever FastAPI routes or Pydantic models change.
