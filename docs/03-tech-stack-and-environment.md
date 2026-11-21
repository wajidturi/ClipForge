# 03 — Technology Stack, Environment & Dependencies

## 1. Stack decisions (and why)

| Layer | Choice | Why |
|---|---|---|
| Backend language | **Python 3.12** | The whole media/AI ecosystem (faster-whisper, MediaPipe, OpenCV, PyAV) is Python-first. 3.12 has wheels for all of them; 3.13+ is not yet safe for MediaPipe/CTranslate2 wheels. |
| API framework | **FastAPI** + Uvicorn | Async, typed (Pydantic v2), auto OpenAPI → generates our TypeScript client. |
| Validation | **Pydantic v2** | One schema for API, DB DTOs, AI structured output. |
| ORM / migrations | **SQLAlchemy 2.x** + **Alembic** | Same code for SQLite and PostgreSQL. |
| Database | **SQLite (WAL)** for local desktop mode · **PostgreSQL 16+** for server mode | Zero-setup locally; real concurrency when hosted. |
| Job queue | **Own DB-backed queue** (jobs table, lease + heartbeat, retries) with worker processes | No Redis needed on a desktop; same interface can be swapped for Redis/Celery at scale (see 04). |
| Realtime | **WebSocket** (FastAPI) for job progress & live chat rate | Replaces polling. |
| Frontend | **React 19 + TypeScript 7 + Vite 8** (as installed in Phase 1) | Mature, typed, fast dev server. |
| UI kit | **Tailwind CSS 4** + own token-based primitives; Radix primitives added for complex widgets (dialogs, menus) | Accessible components, easy theming, dark mode. |
| Data fetching / state | **TanStack Query** (server state) + **Zustand** (UI state) | Caching, retries, invalidation on WS events. |
| Routing / forms | **React Router**, **react-hook-form + zod** | |
| Media UI | HTML5 `<video>`, **wavesurfer.js** (waveform/regions), custom canvas timeline (heat graph, markers) | Trim/caption editor. |
| i18n | **i18next / react-i18next** | RTL support. |
| Calendar | **FullCalendar** (MIT core) | Scheduling view. |
| Media engine | **FFmpeg 7+ / ffprobe** (system binary), **PyAV** for frame access | Industry standard; filters for crop, ASS subtitles (libass), loudnorm, overlays. |
| Download | **yt-dlp** (+ deno for YouTube JS challenge), **streamlink** for live | Broadest site support. |
| Speech-to-text | **faster-whisper** (CTranslate2), models `small`/`medium`/`large-v3-turbo` on GPU, `base` on CPU; built-in Silero VAD | Fast, local, word timestamps, language detection. |
| Vision | **MediaPipe** (face/pose/object), **OpenCV** (YuNet face detector, histograms), **PySceneDetect** (shot cuts) | Reframing, cam detection, moment labels. |
| OCR | **RapidOCR (ONNX)** | Banner text, no Tesseract install. |
| Audio analysis | **numpy / librosa-lite routines**, ffmpeg `ebur128`/`astats` | Loudness, laughter energy, ducking. |
| Translation | **CTranslate2 + Argos/OPUS-MT models** (offline) | No cloud dependency. |
| AI (LLM) | **Provider interface**: Anthropic Claude (default) via official `anthropic` SDK; Ollama (local, free); "No AI" heuristic | See §4. |
| Packaging | Local: one-command launcher + optional **Tauri** desktop shell (Phase 11). Server: **Docker** (CUDA base image) + docker compose | |
| Tooling | **uv** (Python deps/lock), **npm** (JS), **ruff** + **mypy**, **oxlint + Prettier**, **pytest**, **Vitest**, **Playwright**, **pre-commit**, GitHub Actions CI (see ADR 0004) | |

## 2. System requirements

| | Minimum | Recommended |
|---|---|---|
| OS | Windows 10/11, macOS 13+, Ubuntu 22.04+ | Windows 11 / Ubuntu 24.04 |
| CPU | 4 cores | 8+ cores |
| RAM | 8 GB (low-resource mode) | 16–32 GB |
| GPU | none (CPU path) | NVIDIA, 6 GB+ VRAM, driver supporting CUDA 12 (your RTX 4050 qualifies) |
| Disk | 20 GB free | SSD, 100 GB+ (source media + renders) |
| Network | Required for downloads/AI API | |

## 3. Development environment setup (Phase 1 will script this)

Software to install (checked first — only missing items get installed):

| Tool | Version | Notes |
|---|---|---|
| Git | 2.4x+ | enable `core.longpaths=true` on Windows |
| Python | 3.12.x | via `uv python install 3.12` |
| uv | latest | Python env + lockfile |
| Node.js | 22+ (24 in use) | frontend toolchain (npm included) |
| FFmpeg + ffprobe | 7.0+ (you have 9.1 via winget ✔) | must be on PATH |
| NVIDIA driver | CUDA 12-capable | GPU optional |
| Docker Desktop | latest | only for server/deploy testing (Phase 11) |
| VS Code (suggested) | | Python, Ruff, ESLint, Tailwind extensions |

Project layout (monorepo):

```
clipforge/
  backend/         FastAPI app, services, workers, pipeline (Python package `clipforge`)
  frontend/        React + Vite SPA (generated API types in src/lib/api)
  assets/          our own fonts (OFL, from upstream), SFX we synthesise, models fetched at setup
  docs/            these documents + ADRs
  scripts/         setup/dev/doctor scripts (PowerShell + bash)
  docker/          Dockerfiles, compose
  .env.example
```

Environment variables (`.env`, never committed):

| Var | Purpose |
|---|---|
| `CF_MODE` | `local` or `server` |
| `CF_DATA_DIR` | media/data root (default: OS app-data dir) |
| `CF_DATABASE_URL` | `sqlite:///…` or `postgresql+psycopg://…` |
| `CF_SECRET_KEY` | encrypts stored integration secrets / sessions |
| `CF_WORKERS` / `CF_GPU` / `CF_LIGHT_MODE` | resource control |
| `ANTHROPIC_API_KEY` | Claude provider (optional) |
| `CF_OLLAMA_URL` | local LLM (optional) |
| `CF_YTDLP_COOKIES_BROWSER` | bot/age-check workaround (optional) |
| `CF_LOG_LEVEL` | |

## 4. AI model plan

| Task | Default | Alternatives |
|---|---|---|
| Moment selection (Smart/Deep) | Claude **`claude-opus-5-5`**, adaptive thinking, effort set explicitly per route (start `medium`, measure), **structured output** (`output_config.format` / `client.messages.parse()` with our Pydantic `PickList` schema), server-side refusal `fallbacks: "default"` | Ollama local model; No-AI heuristic |
| Hook/title/hashtags | Same call as selection (one request returns everything) | — |
| AI edit instruction → edit plan | Claude with **strict tool use** (`strict: true`) over our edit operations (trim, set_style, set_layout, add_meme, change_hook…) | — |
| Channel diagnosis / ideas | Claude, structured output | — |
| Autopilot bulk runs | **Message Batches API** (50 % cost, async) when latency doesn't matter | — |
| Cost/latency | **Prompt caching** on the frozen system prompt + rules (stable prefix first, transcript last); usage logged per job | — |

Notes: model id is a setting, not hard-coded; the user can choose a cheaper model (e.g. Sonnet/Haiku tier) in Settings — that is a user decision. The Ollama and No-AI paths keep the app fully usable offline/free.

## 5. Dependency list (pin exact versions in Phase 1 with `uv lock` / `pnpm-lock`)

Versions marked ✔ were observed working together in the reference (Nov 2026); others are "latest stable at Phase 1", then locked.

**Backend runtime**
| Package | Version | Use |
|---|---|---|
| fastapi, uvicorn[standard] | latest | API server |
| pydantic, pydantic-settings | v2 | schemas, config |
| sqlalchemy | 2.x | ORM |
| alembic | latest | migrations |
| psycopg[binary] | 3.x | PostgreSQL (server mode) |
| anthropic | latest | Claude provider |
| httpx | latest | HTTP clients (Ollama, platform APIs) |
| cryptography | latest | secret encryption (Fernet) |
| yt-dlp[default,deno] | ✔ 2026.10.26 | downloads |
| streamlink | ✔ 8.6.3 | live recording |
| faster-whisper | ✔ 1.2.1 | transcription |
| av (PyAV) | ✔ 18.1.0 (not 19: breaks faster-whisper 1.2.1) | decoding |
| nvidia-cublas-cu12, nvidia-cudnn-cu12 9.x | ✔ | GPU (optional extra) |
| mediapipe | ✔ 1.2.3 | face/pose/object |
| opencv-contrib-python | ✔ 5.0.0.93 | vision, YuNet |
| scenedetect | latest | shot detection |
| rapidocr-onnxruntime | latest | OCR |
| numpy | latest | |
| pillow, fonttools | latest | covers, text metrics, emoji |
| ctranslate2, sentencepiece, argostranslate (no-deps) | latest | translation |
| websockets | latest | live chat (Twitch IRC/Kick) |
| apscheduler | 3.x | autopilot scheduler |
| psutil | latest | RAM/GPU/disk profiling |
| structlog | latest | structured logs |

**Backend dev:** pytest, pytest-asyncio, pytest-cov, httpx2, ruff, mypy, pre-commit (Phase 1); hypothesis, respx, locust added when first needed.

**Frontend (Phase 1, locked in `package-lock.json`):** react 19, react-dom, typescript 7, vite 8, @tanstack/react-query 5, zustand 5, react-router 8, tailwindcss 4, lucide-react, clsx, tailwind-merge, i18next, react-i18next, openapi-fetch; dev: vitest 5, jsdom, @testing-library/react, user-event, jest-dom, oxlint, prettier. `openapi-typescript` runs via npx (no TypeScript 7 peer support yet). Added in later phases: react-hook-form, zod, Radix primitives, wavesurfer.js, @fullcalendar/react, playwright.

**Assets (fetched from upstream, own licenses):** OFL fonts (Anton, Bebas Neue, Montserrat, Poppins, Bangers, Noto Sans + Arabic/Devanagari/CJK), MediaPipe face/landmarker models (Apache-2.0), YuNet ONNX (MIT/Apache), Whisper models (MIT) downloaded on first use. SFX and music beds are **synthesised by our own code**, not shipped recordings.
