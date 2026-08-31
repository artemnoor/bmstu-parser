# BMSTU frontend

Independent static frontend for the BMSTU Education Data API. It contains no
Python code, parser logic, credentials or dataset files. `api-client.js` is
the only HTTP seam; the dashboard never reads `data/result` directly.

Run locally:

```powershell
python -m http.server 5173 --directory frontend
```

The dashboard uses `http://127.0.0.1:8000` by default when served on port
5173. The API endpoint can be changed in the UI and is kept in local storage.
For Docker, `nginx.conf` proxies API requests to the separate `bmstu-api`
service and Compose is defined in `../infra/docker-compose.yml`.

Install the development browser test dependencies and run the smoke journey:

```powershell
npm ci
npx playwright install chromium
npm run test:e2e
```

The test suite mocks the HTTP seam and verifies API status, navigation, search
and catalog rendering without coupling the frontend to backend files.
