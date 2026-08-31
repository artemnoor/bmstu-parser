# BMSTU education parser

Модульный парсер программ бакалавриата и специалитета с `mirror.bmstu.ru`. Проект разделён на пять этапов:

```text
source API / public plan links
        ↓
raw snapshots → normalization → ontology objects + links → quality gate → JSON / CSV / files
```

## Архитектура и запуск

```powershell
cd BMSTU\backend
python -m pip install -e .
python -m bmstu_parser --output ..\data\result --download-plans --strict
```

Без `--download-plans` ссылки и метаданные учебных планов будут разобраны, но файлы не будут скачаны. Для быстрой проверки можно использовать `--no-resolve-plans`.

Извлечение всех таблиц из уже скачанных планов запускается отдельным блоком:

```powershell
python -m bmstu_parser extract-study-plans --result ..\data\result --workers 6 --strict --verbose
```

По умолчанию используется проверенный native backend (`pdftotext` + `pdfplumber` + `python-docx`). Для экспериментального структурного reader'а можно установить optional extra и явно включить его:

```powershell
python -m pip install -e ".[docling]"
python -m bmstu_parser extract-study-plans --result ..\data\result --reader-backend docling --strict
```

Команда сразу создаёт компактные JSONL/CSV-проекции: исходные PDF/DOCX, layout-текст и полный `study_plan_cells.csv` сохраняются, а Ontology и строки содержат ссылки на эти ячейки. Повторный запуск возобновляется по fingerprint исходного файла и backend'а; для полного перерасчёта используйте `--no-resume`. `compact-study-plans` нужен для старых результатов, созданных предыдущей версией writer'а.

Семантическое извлечение предметов и нагрузки запускается отдельным блоком:

```powershell
python -m bmstu_parser extract-study-plan-semantics --result ..\data\result --strict
```

HTTP API для взаимодействия с datasets и управления операциями запускается так:

```powershell
python -m bmstu_parser api --result ..\data\result --host 127.0.0.1 --port 8000
```

После запуска доступны Swagger UI (`/docs`), ReDoc (`/redoc`) и OpenAPI-контракт (`/openapi.json`). Полное описание endpoints находится в [`docs/API.md`](docs/API.md). Для фоновых операций задайте `BMSTU_API_KEY`; они выполняются последовательно и возвращают наблюдаемый `operation_id`.

Каждый запуск parser/extraction/semantic-stage оставляет манифест в `data/result/pipeline_runs/`: этапы, входы, выходы, SHA-256, счётчики и quality gate. Историю можно запросить через `GET /api/v1/runs`.

Отдельная статическая dashboard-визуализация находится в [`frontend/`](frontend/): она не входит в процесс API и обращается к нему только по HTTP. Запустите API с разрешённым origin и во втором терминале поднимите простой static server:

```powershell
# Терминал 1 — API
$env:BMSTU_CORS_ORIGINS = "http://127.0.0.1:5173,http://localhost:5173"
cd BMSTU\backend
python -m bmstu_parser api --result ..\data\result --host 127.0.0.1 --port 8000

# Терминал 2 — отдельный frontend, из корня репозитория BMSTU
cd BMSTU
python -m http.server 5173 --directory frontend
```

Откройте `http://127.0.0.1:5173`. Панель показывает состояние API, quality reports, направления, образовательные программы, конкретные предметы с нагрузкой, каталог datasets и учебные планы; из неё также можно поставить поддерживаемую операцию в очередь. Короткая инструкция находится в [`docs/WEB.md`](docs/WEB.md).

Он строит записи дисциплин, общей нагрузки, часов по видам занятий, нагрузки по каждому семестру, контрольных форм и обязательности/выборности. Источник каждого поля остаётся доступен через `source_row_id` и `source_cell_ids`.

Для контроля без ручной разметки каждая семестровая запись также сохраняет `raw_bands` — исходный текст пяти PDF-полос до нормализации — и `normalization_notes`. Контрольные обозначения привязываются к координатам начала слова в PDF; если исходная ячейка объединяет соседние полосы, значение не угадывается, а остаётся в raw-слое и получает детерминированную привязку. `study_plan_semantic_report.json` останавливает строгий запуск при потерянных таблицах, неразрешённых контрольных значениях, утечке контроля в числовые поля или предупреждениях схемы.

Если нужно только уплотнить уже созданные производные файлы без потери полного набора ячеек:

```powershell
python -m bmstu_parser compact-study-plans --result ..\data\result
```

## Результат

- `data/result/raw/` — неизменённые ответы списка и карточек;
- `data/result/bmstu_bachelor_majors.json` — канонические записи и встроенная Ontology-модель;
- `data/result/ontology.json` — объекты, свойства, связи и provenance отдельно;
- `data/result/parse_report.json` — quality gate;
- CSV-файлы — проекции для аналитики;
- `data/result/study_plans/` — локальные документы учебных планов.
- `data/result/study_plan_data/study_plan_cells.csv` — полный набор ячеек всех обнаруженных таблиц;
- `data/result/study_plan_data/study_plan_pages.jsonl` — слова, строки и координаты страниц;
- `data/result/study_plan_data/study_plan_tables.jsonl` — манифест таблиц и их границы;
- `data/result/study_plan_data/study_plan_rows.jsonl` — строки и ссылки на ячейки;
- `data/result/study_plan_data/study_plan_ontology.json` — Ontology-слой документов, таблиц, строк, предметов и семестровой нагрузки;
- `data/result/study_plan_data/study_plan_extraction_report.json` — отдельный quality gate извлечения.
- `data/result/study_plan_data/study_plan_disciplines.jsonl` — нормализованные предметы и общая трудоёмкость;
- `data/result/study_plan_data/study_plan_discipline_entities.jsonl` — безопасно разрешённые повторяющиеся предметы без изменения исходных discipline IDs;
- `data/result/study_plan_data/study_plan_semester_load.csv` — предмет × семестр: з.е., часы, аудит, самостоятельная работа и контроль;
- `data/result/study_plan_data/study_plan_curriculum_rows.jsonl` — все строки curriculum-таблиц, включая разделы и группы;
- `data/result/study_plan_data/study_plan_curriculum_schema.json` — обнаруженная схема колонок и число семестров;
- `data/result/study_plan_data/study_plan_semantic_report.json` — quality gate семантического слоя.
- `data/result/study_plan_data/study_plan_resolution_report.json` — aliases, безопасные entity mappings и потенциальные коллизии локальных кодов;
- `data/result/study_plan_data/checkpoints/` — атомарный resumable ledger и промежуточные результаты извлечения.
- `data/result/pipeline_runs/` — история запусков с этапами, входами/выходами, fingerprints и статусом quality gate.

Канонический raw-слой (`study_plan_cells.csv`, `study_plan_pages.jsonl`, `study_plan_tables.jsonl`) хранит исходные PDF-слова, координаты и ячейки. Семантические CSV/JSONL — это проверяемые проекции; при неоднозначности они не придумывают значение, а сохраняют исходник и фиксируют gap в отчёте.

`THIRD_PARTY_NOTICES.md` фиксирует, какие узкие идеи были адаптированы из проверенных upstream-проектов. Вендоринг чужих приложений и замена локальных правил балансировки не выполняются: внешние readers/resolvers проходят через локальные контракты и quality gates.

Полная таблица не дублируется в Ontology JSON: все значения хранятся в `study_plan_cells.csv`, а Ontology и строки ссылаются на `table_id + row_index + column_index`. Это уменьшает дублирование и сохраняет lineage.

Описание parser/backend-модели находится в [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Инструкции приложений — в [`backend/README.md`](backend/README.md), [`frontend/README.md`](frontend/README.md) и [`contracts/README.md`](contracts/README.md).
