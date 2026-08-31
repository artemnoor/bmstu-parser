# University Data Platform API

API является отдельным consumption/control-слоем. Все данные имеют scope
университета; flat endpoints из прежней BMSTU-версии публично удалены.

## Основные endpoints

| Метод | Endpoint | Назначение |
|---|---|---|
| `GET` | `/health` | Состояние сервиса |
| `GET` | `/api/v1/universities` | Университеты и capabilities |
| `GET` | `/api/v1/universities/{university_id}` | Описание университета |
| `GET` | `/api/v1/universities/{university_id}/catalog` | Dataset-каталог и quality |
| `GET` | `/api/v1/universities/{university_id}/datasets` | Allowlist CSV/JSONL datasets |
| `GET` | `/api/v1/universities/{university_id}/datasets/{name}/rows` | Пагинация и фильтры |
| `GET` | `/api/v1/universities/{university_id}/programs` | Канонические программы |
| `GET` | `/api/v1/universities/{university_id}/curricula` | Учебные планы |
| `GET` | `/api/v1/universities/{university_id}/teachers` | Преподаватели |
| `GET` | `/api/v1/universities/{university_id}/departments` | Кафедры, если поддерживаются |
| `GET` | `/api/v1/universities/{university_id}/faculties` | Факультеты, если поддерживаются |
| `GET` | `/api/v1/universities/{university_id}/admission` | Вступительные требования, если поддерживаются |
| `GET` | `/api/v1/universities/{university_id}/tuition` | Стоимость обучения, если поддерживается |
| `POST` | `/api/v1/universities/{university_id}/operations` | Фоновая операция |
| `GET` | `/api/v1/universities/{university_id}/operations/{operation_id}` | Статус операции |

Примеры:

```text
GET /api/v1/universities/bmstu/programs?limit=50
GET /api/v1/universities/fake/datasets/disciplines/rows?q=математика
```

Неизвестный университет возвращает `404` с кодом `university_not_found`.
Отключённая capability возвращает `404` с кодом `capability_unavailable`.
Отсутствующий опубликованный dataset возвращает `503` с кодом
`dataset_not_published`.

## Canonical records

Записи сохраняют плоские значения и служебные поля рядом:

```json
{
  "id": "university:fake:discipline:…",
  "university_id": "fake",
  "name": "Статистика",
  "total_hours": null,
  "field_meta": {
    "total_hours": {
      "status": "not_published",
      "method": "chain",
      "confidence": 0.0,
      "sources": [],
      "warnings": []
    }
  },
  "extensions": {},
  "provenance": {}
}
```

ID строятся из `university_id`, типа сущности и устойчивого business key.
Старые BMSTU ID разрешаются через `id_aliases.json` после migration.

## Operations

Изменяющие операции выполняются последовательно одним worker и сохраняют
статус в persistent job store:

- `refresh` — загрузить источник и пересобрать каталог;
- `extract_study_plans` — извлечь документы и таблицы;
- `extract_semantics` — построить семантические дисциплины и нагрузки;
- `compact_study_plans` — уплотнить производные индексы.

```powershell
$body = @{ operation = "refresh"; strict = $true } | ConvertTo-Json
$job = Invoke-RestMethod `
  http://127.0.0.1:8000/api/v1/universities/fake/operations `
  -Method Post -ContentType "application/json" -Body $body
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/universities/fake/operations/$($job.id)"
```

В production задайте `UNIVERSITY_ENV=production`, `UNIVERSITY_API_KEY` и
явный `UNIVERSITY_CORS_ORIGINS`. Write endpoint принимает `X-API-Key`.

## Storage и migration

```text
data/result/{university_id}/
├── raw/ canonical/ semantic/ quality/ pipeline_runs/
├── ontology.json
└── id_aliases.json
```

Migration не удаляет legacy result:

```powershell
university-data migrate bmstu `
  --from data/result `
  --to data/result/bmstu `
  --rebuild-derived --write-aliases
```
