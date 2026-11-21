# Developer Setup

## 1. Prerequisites

| Tool | Version | Install (Windows) |
|---|---|---|
| Git | 2.4x+ | `winget install Git.Git` |
| uv | 0.13+ | `winget install astral-sh.uv` |
| Node.js | 22+ (24 used) | `winget install OpenJS.NodeJS.LTS` |
| FFmpeg + ffprobe | 7+ | `winget install Gyan.FFmpeg` (then open a new terminal) |
| NVIDIA driver | CUDA 12 capable | optional, only for GPU speed-ups |
| Docker Desktop | latest | optional, for PostgreSQL tests / server mode |

Python 3.12 is installed by uv (`uv python install 3.12`); you do not need a system Python.

> **Windows path length:** keep the project in a short path (e.g. `Desktop\ClipForge`). Python on Windows cannot read files whose full path exceeds 260 characters unless long paths are enabled system-wide, and deep virtual-env folders hit that limit quickly.

## 2. One-time setup

```powershell
.\scripts\setup.ps1
```

It checks the prerequisites, installs Python 3.12 + backend packages (`backend/.venv`), installs the git pre-commit hook, runs `clipforge doctor`, installs frontend packages, and creates `.env` from `.env.example`.

Manual equivalent:

```powershell
cd backend; uv sync --python 3.12; uv run pre-commit install; uv run clipforge doctor
cd ..\frontend; npm ci
```

## 3. Run in development

```powershell
.\scripts\dev.ps1
```

- Backend window: `clipforge dev` = API on http://127.0.0.1:8800 + 2 worker processes.
- Frontend: Vite on **http://localhost:5173** (open this one; it forwards `/api` and the WebSocket to the backend, with hot reload).
- Data (SQLite DB, media, logs) goes to `./data` (git-ignored). Change with `CF_DATA_DIR`.
- API docs: http://127.0.0.1:8800/api/v1/docs

Separate processes, if you prefer:

```powershell
cd backend; uv run clipforge api              # API only
cd backend; uv run clipforge worker --caps cpu,net
cd frontend; npm run dev
```

## 4. Everyday commands

| Task | Backend (`cd backend`) | Frontend (`cd frontend`) |
|---|---|---|
| Tests | `uv run pytest` | `npm test` |
| Lint | `uv run ruff check .` | `npm run lint` |
| Format | `uv run ruff format .` | `npm run format` |
| Types | `uv run mypy` | `npm run typecheck` |
| Build | — | `npm run build` (served by the API from `frontend/dist`) |
| Machine check | `uv run clipforge doctor` | — |
| New migration | `uv run alembic revision --autogenerate -m "what changed"` | — |
| Apply migrations | `uv run clipforge db upgrade` (the API also does this at start) | — |
| Regenerate API types | — | `npm run gen:api` (after changing backend schemas) |
| Update the video downloader | `uv run clipforge update-downloader` | — |
| Real download tests (internet) | `$env:CF_TEST_NETWORK="1"; uv run pytest -m network` | — |

## 5. PostgreSQL tests (optional locally, always in CI)

```powershell
docker run -d --name cf-pg -e POSTGRES_USER=clipforge -e POSTGRES_PASSWORD=clipforge -e POSTGRES_DB=clipforge_test -p 5432:5432 postgres:16
$env:CF_TEST_POSTGRES_URL = "postgresql+psycopg://clipforge:clipforge@localhost:5432/clipforge_test"
cd backend; uv run pytest -m postgres
```

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError` for a file that exists in `.venv` | Path too long: move the project to a shorter folder, delete `backend/.venv`, run `uv sync` again |
| Jobs stay "Queued" | No worker running: use `clipforge dev` or start `clipforge worker` |
| Sidebar shows "Offline – reconnecting" | The backend is not running on port 8800 |
| `clipforge doctor` says ffmpeg missing | Install FFmpeg and open a **new** terminal so PATH refreshes |
| A link fails with "sign-in or bot check" | Wait a few minutes, or set `CF_YTDLP_COOKIES_BROWSER=firefox` (a browser where you are signed in) |
| Links fail with "no formats" / "unsupported" | `uv run clipforge update-downloader` |
