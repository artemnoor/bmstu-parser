# Архитектура University Data Platform

BMSTU — первый plugin, а не граница всей системы. Публичная композиция
находится в `university_data`; конкретные URL, mappings и provider DTO
расположены в `universities/bmstu`. FakeUniversity использует другой набор
источников (JSON/XLSX/teachers) и поэтому проверяет реальную глубину core.

```text
Provider → typed Source DTO → core normalization → resolver chain
        → canonical domain → ontology / quality → namespaced storage → API
```

## Целевой принцип

Архитектура вдохновлена Foundry-подходом Palantir, но не является копированием их продукта. В Foundry Ontology является операционным семантическим слоем поверх наборов данных: сущности представляются объектами, их атрибуты — свойствами, а связи между сущностями — links. Это описано в [официальном обзоре Ontology](https://www.palantir.com/docs/foundry/ontology/overview). Поэтому исходные ответы сайта не смешиваются с прикладной моделью.

У проекта есть четыре независимых представления данных:

1. **Raw** — ответы источника как воспроизводимые снимки.
2. **Transform** — очистка HTML, приведение типов, нормализация названий и ссылок.
3. **Ontology** — устойчивые объекты и связи предметной области.
4. **Projections** — JSON и CSV для конкретных потребителей.

Это близко к идее Foundry, где наборы данных являются фундаментальным представлением, а затем проходят преобразования и отображаются в Ontology; см. [описание datasets](https://www.palantir.com/docs/foundry/data-integration/datasets) и [модель inputs → transforms → outputs](https://www.palantir.com/docs/foundry/pipeline-builder/core-concepts).

## Поток данных

```text
Mirror API                         Yandex public resources
    │                                      │
    ├─ majors list                         ├─ resolve clck.su
    └─ major details                       ├─ enumerate folders
              │                            └─ download documents
              └──────────────┬─────────────┘
                             ↓
                    transform.normalize
                             ↓
                    canonical domain model
                             ↓
                    transform.ontology
                             ↓
                      quality.checks
                             ↓
                   outputs.writers/projections
```

## Каноническая предметная модель

| Сущность | Ontology object | Основной источник |
|---|---|---|
| Университет | `university` | registry/config |
| Направление подготовки | `study_direction` | карточка направления |
| Факультет | `faculty` | список направлений и карточка |
| Кафедра | `department` | `chairs.items[]` карточки |
| Образовательная программа | `program` | `chairs.items[].educationalProgram.items[]` |
| Вступительное требование | `admission_requirement` | `points[]` |
| Вариант стоимости | `tuition_option` | `price[]` |
| Места | `admission_place` | `places[]` |
| Исторический проходной балл | `historical_passing_score` | `chairs.items[].oldPoints.points[]` |
| Дисциплина | `discipline` | `courses.items`, кафедра или программа |
| Партнёр практики | `practice_partner` | `educationalProgram.practice[]` |
| Учебный план | `curriculum` | `educationalProgram.plan` |
| Документ плана | `study_plan_document` | публичный файл Yandex |

Ключевые связи:

- `major_offered_by_faculty`;
- `major_prepared_by_department`;
- `department_part_of_faculty`;
- `department_runs_program`;
- `major_has_educational_program`;
- `program_contains_discipline`;
- `program_has_study_plan` → `study_plan_contains_document`;
- `program_has_practice_partner`;
- связи направления с требованиями, стоимостью, местами и историческими баллами.

Связь «кафедра ведёт программу» создаётся только потому, что программа действительно вложена в ответе API конкретной кафедры. Она не восстанавливается эвристикой по названию. Это важное правило против ложных отношений.

## Идентичность и provenance

Каждый объект получает детерминированный ID вида `university:<university_id>:<type>:<hash>`, вычисленный из устойчивого исходного ключа. Читаемые `slug`, код и название сохраняются отдельными свойствами. В объекте и связи хранится provenance: URL страницы, URL API, время получения и путь raw-снимка.

Такой подход соответствует идее метаданных свойств: у свойства должны быть стабильная идентичность, понятное имя и описание; см. [официальную документацию Palantir по property metadata](https://www.palantir.com/docs/foundry/object-link-types/property-metadata). Для обновления данных можно сравнивать raw-снимки и канонические ID, не привязывая downstream-код к порядку элементов ответа.

## Quality gate

Перед записью результата проверяются:

- provider DTO type, stable `source_key`, real source locator and raw lineage;
- совпадение количества элементов списка с `meta.count` API;
- отсутствие повторяющихся `slug`;
- наличие успешной карточки для каждого элемента списка;
- заполненность названия и кода направления;
- наличие контекста кафедры у каждой программы;
- отсутствие ссылок Ontology на несуществующие объекты;
- ошибки разрешения или скачивания планов.

Статус `resolved_empty` не считается ошибкой: это означает, что публичная папка источника существует, но в ней нет файлов. Все такие случаи остаются видимыми в `parse_report.json`.

## Структура кода

```text
BMSTU/
├── backend/
│   ├── src/university_data/ # core, domain, sources, plugins, API
│   ├── tests/             # backend unit/integration tests
│   ├── pyproject.toml     # isolated Python package
│   └── Dockerfile
├── frontend/              # static client; no Python/data access
├── contracts/             # generated OpenAPI seam
├── infra/                 # separate backend/frontend containers
├── data/                  # backend-owned raw and derived datasets
└── docs/
```

Семантический слой учебных планов намеренно разделён на небольшие модули:
`semantic_geometry` отвечает за координаты и полосы PDF,
`semantic_schema` — за обнаружение схемы таблицы,
`semantic_curriculum` — за классификацию строк, числа и контроль,
`semantic_reconciliation` — за сверку итогов,
`semantic_quality` — за quality gate,
`semantic_io` — за проекции, а `semantic_ontology` — за Ontology projection.
`semantics.py` оставлен фасадом и оркестратором. Такой разрез сохраняет
общие правила балансировки и позволяет тестировать их через отдельные seams.

В API чтение datasets также вынесено за seam: `DatasetRepository` ограничивает
имена и пути allowlist-каталогом и читает namespaced CSV/JSONL построчно. Этот
seam оставляет возможность подключить DuckDB/Parquet для больших каталогов без
изменения маршрутов; файлы остаются каноническим источником и не превращаются
в вторую базу.
`JobManager` принимает абстракцию `JobStore`; production default — SQLite с
восстановлением прерванных операций, а `InMemoryJobStore` используется для
лёгких тестов. `UniversityPipeline` принимает registry и опции источника;
provider seams остаются явными и тестируемыми через constructor injection.

## Plugin contract и capabilities

Static registry регистрирует модули вузов одной строкой на модуль. Новый модуль
предоставляет `UniversityManifest`, mapping `ProviderSet`, resolver registry и
operations. `UniversityPlugin`/`UniversityProviders` остаются compatibility
facade для существующих адаптеров. Manifest хранится в `manifest.yaml` и
содержит только metadata, fixed core capabilities и настройки источника.

Provider возвращает список typed Source DTO или `ProviderResult` с явными
`warnings` и `gaps`. Core capability registry связывает ожидаемый DTO,
canonical datasets, materializer, Ontology type и API names; pipeline, provider
contract, quality и API используют один и тот же registry.

Capability, которую источник не поддерживает, пропускается без искусственных
нулей, попадает в quality как `not_supported`, а scoped API возвращает
`404 capability_unavailable`. Для опубликованного значения `field_meta`
содержит `status=published`; для вычисленного — `derived` и имя resolver;
для отсутствующего — `not_supported`. Partial provider может получить
`degraded` только через `allow_partial`; исключение источника или нарушение
provider contract блокирует новый snapshot и сохраняет предыдущий active.

Связь с capability, которой нет у университета, не превращается в synthetic
Ontology edge: canonical relation остаётся пустой, исходный ключ хранится в
`extensions.<university_id>.unresolved_references`. Если target capability
объявлена, но target record отсутствует, quality gate фиксирует blocking orphan.

ID имеют форму `university:<university_id>:<entity_type>:<hash>`. Hash строится
из устойчивого business key; позиция массива не используется, кроме
детерминированного разрешения настоящей коллизии. `id_aliases.json` связывает
исторические IDs с новыми; aliases scoped по типу сущности и поддерживаются
для любого university plugin.

`UniversityPipeline` не знает URL, JSON-поля или правила BMSTU. BMSTU-specific
raw parsing, mappings и операции учебных планов находятся в
`universities/bmstu/adapter`; на границе plugin они переводятся в `Source*`
DTO и затем материализуются только canonical dataclass-моделями. Балансировка
detail-запросов, общий rate limiter, retry/backoff, checkpoint, atomic writers
и lineage реализованы в platform runtime.

## Отдельный слой учебных планов

Скачанный PDF/DOCX рассматривается как отдельный raw-документ, а не как строка в карточке программы. Команда `university-data extract_study_plans` выполняет следующий поток:

```text
PDF/DOCX bytes + source metadata
            ↓
reader backend (native by default; optional Docling adapter)
            ↓
Poppler/pdfplumber/python-docx or Docling → canonical pages/tables/cells
            ↓
documents → pages → tables → rows → cells
            ↓
semantic curriculum mapping
            ↓
documents → curriculum rows → disciplines → semester loads
            ↓
typed rules + non-destructive entity resolution
            ↓
CSV/JSONL datasets + document/table/row/discipline/entity ontology
```

Для PDF сохраняются layout-текст, все извлечённые слова с координатами, геометрия каждой ячейки и `word_ids`, из которых она собрана. Полный табличный слой находится в `study_plan_cells.csv`; это dataset-слой. Ontology содержит семантические объекты документа, таблицы и строк, а не копирует миллион ячеек внутрь каждого объекта. Такой раздельный pipeline соответствует принципу Foundry «inputs → transforms → outputs» и отделению dataset от семантического слоя ([официальная документация Palantir](https://www.palantir.com/docs/foundry/data-integration/datasets)).

Команда `university-data extract_semantics` поверх этого dataset-слоя распознаёт curriculum-заголовки и строит типизированные записи:

- предмет: код, название, кафедра, обязательность/выборность и путь разделов;
- общая трудоёмкость: з.е., общее количество часов, аудиторные часы;
- виды занятий: лекции, семинары, лабораторные и самостоятельная/иная работа;
- каждый семестр: недели, з.е., часы, аудиторная и самостоятельная нагрузка;
- контроль: исходная форма (`Зчт`, `Экз`, `ДЗчт`, `РЭкз`, `КуР`, `КуП`, `ГЭК`, `ЭК`) и нормализованные control kinds;
- `raw_bands` и `normalization_notes`: исходный текст пяти семестровых полос и объяснение детерминированной нормализации объединённых ячеек;
- lineage: `source_row_id`, `source_cell_ids`, исходный CSV и исходный документ.

Семестровая схема не зашита одним фиксированным числом: она извлекается из заголовка конкретного документа. Поддержаны варианты на 10, 12 и 14 семестров. Если в исходном плане общая нагрузка указана, но числовая семестровая нагрузка не распределена (например, у альтернативного электива), это фиксируется как `unallocated`, а не теряется и не считается ошибкой.

Для PDF с объединёнными ячейками контрольная форма разрешается по координате начала PDF-слова, а порядок слов сначала стабилизируется по `(top, x0, id)`. Поэтому результат не зависит от порядка обхода объектов и не требует ручного выбора ячейки. Сырой текст и координаты при этом остаются в dataset-слое.

Quality gate учебных планов проверяет каноническое число документов, прикрепление всех ссылок манифеста к документам, количество физических файлов, сигнатуры PDF/DOCX, наличие таблиц у каждого PDF, наличие layout-текста, совпадение размера и SHA-256 с метаданными Yandex, отсутствие неразрешённых файлов и наличие materialized rows/cells. Один публичный документ может быть связан с несколькими программами: он извлекается один раз по детерминированному `document_id`, а все исходные ссылки сохраняются в `source_references` и Ontology links.

API является отдельным consumption/control-слоем поверх этих datasets. Он не дублирует extraction-логику: read endpoints читают allowlist datasets построчно, а operation endpoints запускают существующие pipeline через university-scoped job store: разные вузы могут выполняться параллельно, но для одного вуза одновременно допускается одна изменяющая операция. Backend можно вынести в отдельный контейнер, подключив `data/result` как volume.

Статическая визуализация `frontend/` является отдельным клиентским слоем и не входит в контейнер API. В Docker nginx проксирует `/api` и `/health` во внутренний backend, поэтому браузер работает same-origin; при отдельной раздаче frontend использует явный CORS backend'а. Raw-файлы frontend не получает.

## Контракт этапов и локальная lineage-модель

Архитектура повторяет полезную часть модели Foundry, но не является самим Palantir Foundry. В Foundry pipeline связывает входные datasets, transforms, outputs и data expectations; Ontology предоставляет прикладной слой объектов и связей поверх данных. В BMSTU этому соответствуют следующие этапы:

```text
ingest                 raw snapshots / downloaded documents
    ↓
extract_documents      pages → tables → rows → cells
    ↓
semantic_transform     curriculum rows → disciplines → semester loads
    ↓
ontology_projection    typed objects + links + provenance
    ↓
quality_gate           expectations, reconciliation, referential integrity
    ↓
API / web projections   read-only datasets and controlled operations
```

Каждый исполняемый этап теперь пишет `data/result/{university_id}/pipeline_runs/<run_id>.json`. В манифесте фиксируются статус, время, входные и выходные артефакты, размер, SHA-256, ключевые счётчики и результат quality gate; `latest.json` указывает последний запуск. Это делает запуск воспроизводимым и позволяет отличать «файл существует» от «файл получен конкретным преобразованием».

Извлечение документов дополнительно ведёт атомарный checkpoint ledger. Результат переиспользуется только при совпадении fingerprint файла, локальной ссылки, ожидаемых metadata и backend'а. Запись нового JSON/CSV проходит через соседний временный файл с заменой назначения после успешного закрытия; сбой не оставляет частично записанный dataset.

`quality_gate` разделяет блокирующие ошибки и исходные gaps. Например, отсутствие семестровой раскладки у альтернативного электива не подменяется нулём: исходная общая нагрузка сохраняется, gap попадает в отчёт, а строгие проверки останавливают запуск при потере таблиц, строк, ячеек, контролей или ссылок. Дополнительно проверяется соответствие заявленных `document/table` counts фактически materialized rows/cells и точное покрытие detail-запросами всех элементов исходного списка.

Статус фонового запуска доступен через `GET /api/v1/universities/{university_id}/operations/{operation_id}`. Это локальный control-plane проекта, а не попытка имитировать внутренние сервисы Foundry; для production остаются отдельные задачи: расписание, внешние метрики и авторизация пользователей.

Для инженерного quality gate репозитория CI запускает Ruff lint/format,
проверку типов для изменяемого ядра, pytest с покрытием критических модулей,
Docker build с проверкой `pdftotext` и Playwright smoke-test независимого
frontend. Полный список локальных команд находится в README backend.
