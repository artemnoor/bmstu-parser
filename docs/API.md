# BMSTU Education Data API

Микросервис предоставляет REST-доступ к результатам парсера и управлению длительными операциями. Он не заменяет основной pipeline: API вызывает существующие `ScrapePipeline`, `StudyPlanExtractionPipeline`, semantic extraction и compaction.

## Запуск

Из каталога `BMSTU`:

```powershell
cd backend
python -m pip install -e .
python -m bmstu_parser api --result ..\data\result --host 127.0.0.1 --port 8000
```

Также доступен `bmstu-api` после `pip install -e .`; раздельный backend/frontend запускается через Docker Compose:

```powershell
cd ..
docker compose -f infra\docker-compose.yml up --build
```

Документация генерируется автоматически:

- Swagger UI: `http://127.0.0.1:8000/docs`;
- ReDoc: `http://127.0.0.1:8000/redoc`;
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`.

## Read API

| Метод | Endpoint | Назначение |
|---|---|---|
| `GET` | `/health` | Состояние сервиса и quality gate |
| `GET` | `/api/v1/catalog` | Dataset-каталог и полные quality reports |
| `GET` | `/api/v1/quality` | Отчёты качества без доступа к файловой системе |
| `GET` | `/api/v1/runs` | История запусков этапов и их lineage |
| `GET` | `/api/v1/runs/{run_id}` | Один манифест запуска с входами, выходами и fingerprints |
| `GET` | `/api/v1/datasets` | Список доступных CSV/JSONL datasets |
| `GET` | `/api/v1/datasets/{name}/rows` | Универсальная пагинация и фильтры |
| `GET` | `/api/v1/majors` | Направления подготовки |
| `GET` | `/api/v1/majors/{slug}` | Одно направление |
| `GET` | `/api/v1/programs` | Образовательные программы |
| `GET` | `/api/v1/programs/{id}` | Одна программа |
| `GET` | `/api/v1/study-plans/documents` | Документы учебных планов |
| `GET` | `/api/v1/study-plans/documents/{id}` | Метаданные документа |
| `GET` | `/api/v1/study-plans/documents/{id}/tables` | Таблицы документа |
| `GET` | `/api/v1/study-plans/documents/{id}/disciplines` | Дисциплины документа |
| `GET` | `/api/v1/study-plans/documents/{id}/file` | Безопасная выдача исходного PDF/DOCX |

`GET /health` возвращает также `data_engine`: фактически выбранный reader
(`duckdb` или `file`). По умолчанию используется DuckDB; режим `file` можно
включить через `BMSTU_DATA_ENGINE=file`.

Универсальный dataset endpoint поддерживает `offset`, `limit` (до 500), `q`, а также точные фильтры `id`, `document_id`, `table_id`, `discipline_id`, `major_id`, `program_id`, `department_id`, `slug`.

Пример:

```text
GET /api/v1/datasets/study_plan_semester_load/rows?document_id=bmstu:study-plan-document:...&limit=100
```

Слой `study_plan_cells` также доступен через тот же endpoint. DuckDB выполняет
count/page/filter/search непосредственно по CSV/JSONL, поэтому сервис не
загружает все 1+ млн ячеек в память.

## Управление операциями

Изменяющие операции выполняются в фоне и сериализуются: одновременно может выполняться только одна. Ответ `202 Accepted` содержит `id`, который используется для polling:

```powershell
$body = @{ operation = "extract_semantics"; strict = $true } | ConvertTo-Json
$job = Invoke-RestMethod http://127.0.0.1:8000/api/v1/operations `
  -Method Post -ContentType "application/json" -Body $body
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/operations/$($job.id)"
```

Поддерживаются операции:

- `refresh` — обновить список направлений и карточки через Mirror API; `download_plans=true` включает скачивание файлов;
- `extract_study_plans` — извлечь таблицы, строки, ячейки и координаты из локальных документов;
- `extract_semantics` — построить дисциплины, нагрузку по семестрам и контрольные формы;
- `compact_study_plans` — уплотнить производные индексы без удаления канонического набора ячеек.

Для `extract_study_plans` можно передать `reader_backend: "native" | "docling"` и `resume: true | false`. `native` используется по умолчанию; `resume` повторно использует только результат с совпадающим fingerprint файла, параметров источника и reader backend.

Для production задайте `BMSTU_ENV=production`, `BMSTU_API_KEY` и явный `BMSTU_CORS_ORIGINS`. Тогда `POST /api/v1/operations` принимает только заголовок `X-API-Key`. Read endpoints остаются доступными отдельно. В development локально разрешены `http://127.0.0.1:5173`, `http://localhost:5173` и origin `null` для открытия `frontend/index.html` напрямую.

Состояние операций хранится в `data/result/pipeline_runs/operations.sqlite3`.
После перезапуска незавершённые `queued`/`running` операции переводятся в
`failed`, а старые записи удаляются по ограниченному TTL/размеру. В текущем
процессе работает один worker и один writer; это гарантирует сериализацию
операций, но для нескольких экземпляров API потребуется общее хранилище
очереди. Параметры хранения настраиваются через
`BMSTU_OPERATION_MAX_RECORDS` и `BMSTU_OPERATION_TTL_SECONDS`.

Изменение идентичности не ломает старые ссылки: pipeline создаёт
`id_aliases.json` с соответствиями `legacy_id → canonical_id`, а dataset API
принимает оба варианта для поддерживаемых сущностей. Новый ID строится из
устойчивого бизнес-ключа, а позиция в массиве используется только как
детерминированный fallback при настоящей коллизии.

## Принципы безопасности и целостности

- пользователь не передаёт путь к файлу: скачивание разрешено только внутри `data/result/study_plans`;
- все dataset names проходят через allowlist;
- пагинация ограничивает размер ответа;
- операции не выполняются параллельно и возвращают статус quality gate;
- исходные PDF/DOCX, cells, words и provenance остаются в существующем raw-слое;
- API не использует OCR и не меняет значения при чтении.
