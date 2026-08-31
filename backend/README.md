# University Data Platform backend

Backend содержит публичный пакет `university_data` и временный пакет
совместимости `bmstu_parser`. BMSTU остаётся первым адаптером, FakeUniversity
проверяет, что core не зависит от формата одного источника.

## Install and run

```powershell
python -m pip install -e ".[dev]"
university-data --university fake --output ..\data\result
university-api --result ..\data\result --host 127.0.0.1 --port 8000
```

Для BMSTU live refresh сохраняется текущий balanced pipeline:

```powershell
university-data --university bmstu --output ..\data\result --download-plans
```

Migration существующего результата выполняется из raw snapshots и не удаляет
источник:

```powershell
university-data migrate bmstu --from ..\data\result --to ..\data\result\bmstu `
  --rebuild-derived --write-aliases
```

## Quality checks

```powershell
ruff check src tests
ruff format --check src tests
python -m mypy src/university_data
python -m pytest -q
```

Runtime dependencies включают `openpyxl` для XLSX без Excel/LibreOffice и
`PyYAML` для strict plugin config. Native PDF reader использует Poppler,
который устанавливается Dockerfile.

Общие retry/backoff, thread-safe rate limiter, per-thread HTTP sessions,
balanced detail workers, atomic `.part` downloads, checkpoint/resume и
lineage реализованы в `university_data` runtime и подключаются через source
seams; BMSTU adapter не меняет их поведение.
