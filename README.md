# University Data Platform

Платформа интеграции университетских данных. BMSTU подключён первым plugin-адаптером, а FakeUniversity служит архитектурным fixture-плагином:

```text
source API / public plan links
        ↓
Provider DTO → normalization → resolver → canonical domain → ontology → quality gate → namespaced storage
```

Публичный namespace — `university_data`; старый `bmstu_parser` оставлен временным compatibility-фасадом для уже работающих интеграций. Общие retry, rate limiter, балансировка workers, checkpoint/resume, atomic writers и lineage сохранены.

## Университеты и layout

```text
src/university_data/
├── core/             # contracts, capabilities, registry, typed config
├── domain/           # University, StudyDirection, Program, Teacher, Curriculum…
├── sources/          # HTTP, PDF/DOCX, XLSX, public-file extractors
├── normalization/    # source DTO → flat canonical values + field_meta
├── resolvers/        # typed Resolution chains
├── ontology/ quality/ storage/ api/
└── universities/
    ├── bmstu/        # Mirror API/Yandex-specific adapter
    └── fake/         # JSON + XLSX + teachers fixture adapter
```

Результаты разделены по scope:

```text
data/result/{university_id}/
├── raw/ canonical/ semantic/ quality/ pipeline_runs/
├── ontology.json
└── id_aliases.json
```

## Архитектура и запуск

```powershell
cd BMSTU\backend
python -m pip install -e .
university-data --university fake --output ..\data\result
university-data --university bmstu --output ..\data\result --download-plans --strict
```

Для разработки установите quality-инструменты:

```powershell
python -m pip install -e ".[dev]"
ruff check src tests
ruff format --check src tests
python -m pytest -q
```

Без `--download-plans` ссылки и метаданные учебных планов будут разобраны, но файлы не будут скачаны. Для быстрой проверки можно использовать `--no-resolve-plans`.

Извлечение всех таблиц из уже скачанных планов запускается отдельным блоком:

```powershell
python -m bmstu_parser extract-study-plans --result ..\data\result\bmstu --workers 6 --strict --verbose
```

По умолчанию используется проверенный native backend (`pdftotext` + `pdfplumber` + `python-docx`). Для экспериментального структурного reader'а можно установить optional extra и явно включить его:

```powershell
python -m pip install -e ".[docling]"
python -m bmstu_parser extract-study-plans --result ..\data\result\bmstu --reader-backend docling --strict
```

Команда сразу создаёт компактные JSONL/CSV-проекции: исходные PDF/DOCX, layout-текст и полный `study_plan_cells.csv` сохраняются, а Ontology и строки содержат ссылки на эти ячейки. Повторный запуск возобновляется по fingerprint исходного файла и backend'а; для полного перерасчёта используйте `--no-resume`. `compact-study-plans` нужен для старых результатов, созданных предыдущей версией writer'а.

Семантическое извлечение предметов и нагрузки запускается отдельным блоком:

```powershell
python -m bmstu_parser extract-study-plan-semantics --result ..\data\result\bmstu --strict
```

HTTP API для взаимодействия с namespaced datasets и управления операциями запускается так:

```powershell
university-api --result ..\data\result --host 127.0.0.1 --port 8000
```

Пересборка существующего BMSTU result из raw snapshots:

```powershell
university-data migrate bmstu `
  --from ..\data\result `
  --to ..\data\result\bmstu `
  --rebuild-derived --write-aliases
```

После запуска доступны Swagger UI (`/docs`), ReDoc (`/redoc`) и OpenAPI-контракт (`/openapi.json`). Полное описание endpoints находится в [`docs/API.md`](docs/API.md). Все публичные пути начинаются с `/api/v1/universities/{university_id}`; для фоновых операций задайте `UNIVERSITY_API_KEY`.

API читает CSV/JSONL через namespaced repository, не отдавая frontend доступ к
файловой системе. Состояние фоновых операций сохраняется в persistent SQLite
job store; незавершённые операции после перезапуска помечаются как прерванные,
а история ограничивается по TTL и размеру. Лимиты настраиваются через
`UNIVERSITY_OPERATION_MAX_RECORDS` и `UNIVERSITY_OPERATION_TTL_SECONDS`.

После нормализации рядом с основным результатом создаётся
`data/result/{university_id}/id_aliases.json`. Он сохраняет соответствия старых и новых ID:
новые идентификаторы устойчивы к перестановке элементов API, а позиционный
fallback применяется только при коллизии. В canonical domain числовые поля
типизированы, но исходные значения и предупреждения не теряются. Ontology
provenance накапливает список `sources` при слиянии наблюдений.

Каждый запуск parser/extraction/semantic-stage оставляет манифест в `data/result/{university_id}/pipeline_runs/`: этапы, входы, выходы, SHA-256, счётчики и quality gate. Статус фоновой операции запрашивается через scoped operation endpoint.

Отдельная статическая dashboard-визуализация находится в [`frontend/`](frontend/): она не входит в процесс API и обращается к нему только по HTTP. Запустите API с разрешённым origin и во втором терминале поднимите простой static server:

```powershell
# Терминал 1 — API
$env:UNIVERSITY_CORS_ORIGINS = "http://127.0.0.1:5173,http://localhost:5173"
cd BMSTU\backend
university-api --result ..\data\result --host 127.0.0.1 --port 8000

# Терминал 2 — отдельный frontend, из корня репозитория BMSTU
cd BMSTU
python -m http.server 5173 --directory frontend
```

Откройте `http://127.0.0.1:5173`. Панель показывает состояние API, quality reports, направления, образовательные программы, конкретные предметы с нагрузкой, каталог datasets и учебные планы; из неё также можно поставить поддерживаемую операцию в очередь. Короткая инструкция находится в [`docs/WEB.md`](docs/WEB.md).

Семантический слой строит записи дисциплин, общей нагрузки, часов по видам занятий, нагрузки по каждому семестру, контрольных форм и обязательности/выборности. Источник каждого поля остаётся доступен через `source_row_id` и `source_cell_ids`.

Для контроля без ручной разметки каждая семестровая запись также сохраняет `raw_bands` — исходный текст пяти PDF-полос до нормализации — и `normalization_notes`. Контрольные обозначения привязываются к координатам начала слова в PDF; если исходная ячейка объединяет соседние полосы, значение не угадывается, а остаётся в raw-слое и получает детерминированную привязку. `study_plan_semantic_report.json` останавливает строгий запуск при потерянных таблицах, неразрешённых контрольных значениях, утечке контроля в числовые поля или предупреждениях схемы.

Если нужно только уплотнить уже созданные производные файлы без потери полного набора ячеек:

```powershell
python -m bmstu_parser compact-study-plans --result ..\data\result
```

## Результат

- `data/result/{university_id}/raw/` — неизменённые ответы списка и карточек;
- `data/result/{university_id}/canonical/` — плоские канонические записи;
- `data/result/{university_id}/ontology.json` — объекты, свойства, связи и provenance отдельно;
- `data/result/{university_id}/quality/` — quality reports;
- `data/result/{university_id}/study_plans/` — локальные документы учебных планов;
- `data/result/{university_id}/study_plan_data/study_plan_cells.csv` — полный набор ячеек всех обнаруженных таблиц;
- `data/result/{university_id}/study_plan_data/study_plan_pages.jsonl` — слова, строки и координаты страниц;
- `data/result/{university_id}/study_plan_data/study_plan_tables.jsonl` — манифест таблиц и их границы;
- `data/result/{university_id}/study_plan_data/study_plan_rows.jsonl` — строки и ссылки на ячейки;
- `data/result/{university_id}/study_plan_data/study_plan_ontology.json` — Ontology-слой документов, таблиц, строк, предметов и семестровой нагрузки;
- `data/result/{university_id}/study_plan_data/study_plan_extraction_report.json` — отдельный quality gate извлечения;
- `data/result/{university_id}/study_plan_data/study_plan_disciplines.jsonl` — нормализованные предметы и общая трудоёмкость;
- `data/result/{university_id}/study_plan_data/study_plan_discipline_entities.jsonl` — безопасно разрешённые повторяющиеся предметы без изменения исходных discipline IDs;
- `data/result/{university_id}/study_plan_data/study_plan_semester_load.csv` — предмет × семестр: з.е., часы, аудит, самостоятельная работа и контроль;
- `data/result/{university_id}/study_plan_data/study_plan_curriculum_rows.jsonl` — все строки curriculum-таблиц, включая разделы и группы;
- `data/result/{university_id}/study_plan_data/study_plan_curriculum_schema.json` — обнаруженная схема колонок и число семестров;
- `data/result/{university_id}/study_plan_data/study_plan_semantic_report.json` — quality gate семантического слоя;
- `data/result/{university_id}/study_plan_data/study_plan_resolution_report.json` — aliases, безопасные entity mappings и потенциальные коллизии локальных кодов;
- `data/result/{university_id}/study_plan_data/checkpoints/` — атомарный resumable ledger и промежуточные результаты извлечения;
- `data/result/{university_id}/pipeline_runs/` — история запусков с этапами, входами/выходами, fingerprints и статусом quality gate.

Канонический raw-слой (`study_plan_cells.csv`, `study_plan_pages.jsonl`, `study_plan_tables.jsonl`) хранит исходные PDF-слова, координаты и ячейки. Семантические CSV/JSONL — это проверяемые проекции; при неоднозначности они не придумывают значение, а сохраняют исходник и фиксируют gap в отчёте.

`THIRD_PARTY_NOTICES.md` фиксирует, какие узкие идеи были адаптированы из проверенных upstream-проектов. Вендоринг чужих приложений и замена локальных правил балансировки не выполняются: внешние readers/resolvers проходят через локальные контракты и quality gates.

Полная таблица не дублируется в Ontology JSON: все значения хранятся в `data/result/{university_id}/study_plan_data/study_plan_cells.csv`, а Ontology и строки ссылаются на `table_id + row_index + column_index`. Это уменьшает дублирование и сохраняет lineage.

Описание parser/backend-модели находится в [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Инструкции приложений — в [`backend/README.md`](backend/README.md), [`frontend/README.md`](frontend/README.md) и [`contracts/README.md`](contracts/README.md).

В Docker native PDF reader готов к работе из коробки: backend image содержит
`poppler-utils` и проверяется в CI вызовом `pdftotext -v`.
