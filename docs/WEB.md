# BMSTU Data Console

`frontend/` — независимый статический frontend для BMSTU Education Data API.
В нём нет Python-кода, базы данных или копии datasets: браузер получает
данные через REST API backend.

## Запуск

Сначала запустите API из каталога `BMSTU\backend`:

```powershell
$env:BMSTU_CORS_ORIGINS = "http://127.0.0.1:5173,http://localhost:5173"
cd BMSTU\backend
python -m bmstu_parser api --result ..\data\result --host 127.0.0.1 --port 8000
```

Во втором терминале, из корня репозитория `BMSTU`, запустите static server:

```powershell
cd BMSTU
python -m http.server 5173 --directory frontend
```

После этого откройте <http://127.0.0.1:5173>.

Адрес API можно изменить прямо в поле `API endpoint` в верхней панели.
Значение сохраняется в `localStorage` браузера.

## Что показывает панель

- состояние API и quality gate по всем отчётам;
- направления подготовки и образовательные программы;
- постраничный список дисциплин и учебных планов;
- каталог разрешённых CSV/JSONL datasets;
- детали направления, программы или учебного плана;
- ссылку на исходный PDF учебного плана;
- постановку поддерживаемой операции в очередь API и наблюдение за её статусом.

## Принцип интеграции

```text
frontend/index.html + api-client.js + app.js + styles.css
                │ fetch()
                ▼
http://127.0.0.1:8000
                │
                ▼
BMSTU/data/result
```

Frontend не изменяет raw-файлы напрямую и не интерпретирует PDF
самостоятельно. Изменяющие действия проходят через контролируемые операции
backend-сервиса.
