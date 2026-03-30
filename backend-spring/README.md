# Spring Backend

`backend-spring` is now the public backend entry for the project.

## What changed

- The frontend remains a separate Vite + React application.
- The public backend is now a Spring Boot service on port `7800`.
- The original Python FastAPI backend is preserved as a legacy capability layer for inference, training, dataset import, and AI advice.
- Spring proxies the existing API contract without changing frontend routes or payload shapes.

## Local run

From the repository root:

```powershell
./start_backend.ps1
./start_frontend.ps1
```

`start_backend.ps1` builds a runnable jar first and then starts it with `java -jar`, which is more reliable here than `spring-boot:run`.

By default:

- Spring Boot listens on `http://127.0.0.1:7800`
- The legacy Python backend is auto-started on `http://127.0.0.1:7801`
- The frontend dev server stays on `http://127.0.0.1:5500`

## Important environment variables

- `SPRING_SERVER_PORT`
- `LEGACY_BACKEND_BASE_URL`
- `LEGACY_BACKEND_AUTO_START`
- `LEGACY_BACKEND_PORT`
- `LEGACY_BACKEND_WORKING_DIRECTORY`
- `LEGACY_BACKEND_PYTHON_PATH`

## Docker

Production compose now runs:

- `legacy-backend`: the existing Python service
- `backend`: the Spring gateway
- `frontend`: the static frontend served by Nginx

