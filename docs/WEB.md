# Web console

Frontend — отдельный статический клиент. Он не читает файлы данных и работает
только через scoped University Data API.

## Local run

```powershell
# terminal 1
cd backend
university-api --result ..\data\result --host 127.0.0.1 --port 8000

# terminal 2
cd ..
python -m http.server 5173 --directory frontend
```

Откройте `http://127.0.0.1:5173`. Selector университета загружает registry,
после переключения UI использует `/api/v1/universities/{university_id}/...`.
Разделы и capability badges учитывают `not_supported`; отсутствие
опубликованного поля не отображается как искусственный ноль.

Для frontend-тестов:

```powershell
cd frontend
npm ci
npx playwright test
```
