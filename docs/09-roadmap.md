# 09 — Development Roadmap (Phase by Phase)

Each phase ends with a **demo + review gate**: you see it working before the next phase starts. Durations assume one full-time developer working with Claude; they are estimates.

| Phase | Name | Depends on | Est. |
|---|---|---|---|
| 0 | Research & planning (this document set) | — | done |
| 1 | Foundation & dev environment | 0 | **done** |
| 2 | Ingestion | 1 | **done** |
| 3 | Transcription & signals | 2 | **done** |
| 4 | Moment selection (no-AI + AI) | 3 | **done** (Ollama; Claude provider pending a key) |
| 5 | Rendering engine core + QC | 4 | **core done** (see docs/pipeline/render.md for open items) |
| 6 | Web app: dashboard, library, review, studio, onboarding | 1 (API), 5 | **core done** (Playwright E2E open; see docs/pipeline/studio.md) |
| 7 | Creators, discovery & live | 3, 6 | 1.5 wk |
| 8 | Formats, FX, voice, translation, branding | 5, 6 | 1.5–2 wk |
| 9 | Scheduling, publishing, autopilot, insights | 6 | 1.5 wk |
| 10 | Hardening, optimization, polish | all | 1–1.5 wk |
| 11 | Packaging & deployment | 10 | 1 wk |

**MVP = end of Phase 6** (paste a link → get reviewed, editable, exportable Shorts with AI or no-AI picks).

---

### Phase 1 — Foundation ✅ (done 2026-11-21)
**Result:** 33 backend + 8 frontend tests green; migrations verified up/down on SQLite (the PostgreSQL migration test is in CI, not yet run locally); job progress, cancel and retry verified live in the browser. Decisions: ADR 0001–0004.

**Tasks:** monorepo scaffold (backend/frontend/packages/docs/scripts); uv + Python 3.12 env; pnpm + Vite React TS; FastAPI skeleton (`/health`, `/system`); settings (pydantic-settings); SQLAlchemy + Alembic with initial schema (05); job queue + worker runtime + WebSocket progress; structlog; `doctor` script (ffmpeg, GPU, disk); pre-commit, ruff, mypy, eslint, vitest, pytest; CI pipeline; OpenAPI → TS client generation; README + setup docs.
**Deliverables:** `pnpm dev` + `uv run clipforge dev` start everything; a dummy job shows live progress in the UI; CI green.
**Exit criteria:** tests pass on Windows + Linux; schema migrates on SQLite and Postgres.

### Phase 2 — Ingestion ✅ (done 2026-11-21)
**Result:** links from 11 platforms + file uploads → audio on disk, with windows, dedupe, retries with fix hints, cancel, delete, segment cache, Sources page with live progress. 123 backend + 15 frontend tests, plus 3 manual network tests; real YouTube download verified (exact 10.000 s window in the browser flow). Found and fixed a silent timestamp-offset bug in windowed audio downloads (see docs/pipeline/ingest.md). Uploads with a drag-and-drop UI are covered by API tests but were not clicked through in the browser.

**Tasks:** URL resolver; yt-dlp metadata + audio download with windows; local upload; segment download; retries/timeouts/cookie option; sources API + list page (basic); media asset store.
**Deliverables:** add a link/file → source appears with metadata and audio.
**Exit:** 10 platform URLs from the list downloaded in tests (recorded fixtures for CI).

### Phase 3 — Transcription & signals
**Tasks:** faster-whisper runner (GPU/CPU), language detection, sentence builder; loudness; chat replay (Twitch/YouTube/Kick) + spikes; clips; replay heatmap; proxy generation; visual moments; shot cuts; banner OCR; HEAT score; source timeline API.
**Deliverables:** source page shows transcript + heat graph + markers.
**Exit:** transcription RTF and signal unit tests meet targets; heat ranking sanity-checked on the eval set.

### Phase 4 — Moment selection
**Tasks:** windows & candidates; no-AI picker; AI provider interface; Claude provider (structured output, prompt caching, refusal fallback, usage logging); Ollama provider; validation loop; callback finder; preview strips; picks editor API; eval harness (precision@N).
**Deliverables:** run produces a reviewed pick list with hooks/titles (Free and Smart modes).
**Exit:** eval baseline recorded; AI output always schema-valid.

### Phase 5 — Rendering core + QC
**Tasks:** reframe (tracking, layouts crop/stack/bubble/full/grid, cam & overlay & letterbox detection); speech editing (EDL); captions engine + 5 core styles; hook/theme overlays; zoom; audio chain (denoise, loudnorm); image fixes; NVENC/x264 encode; cover; aspects; contact sheet; QC + auto re-cut; render orchestrator with parallelism.
**Deliverables:** full pipeline link → finished MP4s with QC.
**Exit:** golden-media tests pass; render time target met on your GPU.

### Phase 6 — Web app (MVP) ✅ core (2026-11-23)
**Result:** library, review queue with hotkeys, Short studio (post, trim, captions, look, AI edit; every render kept as a version), single and per-run ZIP export with post texts, dashboard counts, settings stored in the database over `.env`, first-run setup. 225 backend + 28 frontend tests; checked by hand in the browser including a real Ollama AI edit → re-render. Open: Playwright E2E, create-wizard dry run, contact sheet, manual crop position. Details: docs/pipeline/studio.md.

**Tasks:** app shell, theme, i18n; onboarding; dashboard; create-run wizard with dry run; run detail with live progress; library; review queue with hotkeys; Short studio (preview, trim, captions, look, post tabs); versioning & re-render; manual edit; AI edit; export/ZIP; settings (AI, processing, storage).
**Deliverables:** complete MVP usable end-to-end in the browser.
**Exit:** Playwright E2E green; usability pass.

### Phase 6b — Gaming templates & customisation studio ✅ (2026-11-23)
**Result:** five gaming templates with attractive defaults, scene-based rendering with a cached cut (re-render = compose only), a live canvas studio matching the export (logo upload, text, emojis, 14 stickers, captions, effects, template-aware controls, drag/resize, undo/redo), one-click Create (whole clip + template), Review & customise after rendering. ADR 0006, docs/pipeline/templates.md.

### Phase 6c — Long videos ✅ (2026-11-24)
**Result:** videos up to 12 h used whole (was 4 h → last 2 h), up to 50 Shorts per run with a fair share per source (was 2 per source, 20 per run), length presets (15–60 s, 30–90 s, whole scenes up to 3 min; QC allows 180 s), fast downloads (whole files instead of ffmpeg sections for whole videos and parts over 30 min, live progress, throttle recovery), uploads up to 60 GB, sharp 1080p crops (link moments fetched up to 4K, 1080p editor preview).

### Phase 7 — Creators, discovery & live
**Tasks:** creators CRUD + clip policies; discovery rules (RSS/search/category); past-streams lists; live recorder ring buffer; live chat readers; spike → candidate → render; live hunt; live page.
**Exit:** 1-hour soak test on a real live stream without leaks.

### Phase 8 — Formats & effects
**Tasks:** formats (callback, compilation, escalation, then-vs-now, reveal, chat overlay, wait-for-it); all ~30 caption styles; meme moods + synthesised SFX; music beds + ducking; voice-over (browser recording); offline translation + RTL/CJK; branding (watermark, progress bar, end card); brand page.
**Exit:** every format/style/mood has a golden test and a preview image.

### Phase 9 — Scheduling, publishing, automation, insights
**Tasks:** schedule planner + calendar + CSV; publisher interface + YouTube upload (OAuth) with preview/confirm; integration secrets encryption + test; autopilot scheduler with preview; insights (stats, diagnosis, learning rules).
**Exit:** scheduled upload to a test channel succeeds only after confirm.

### Phase 10 — Hardening & optimization
**Tasks:** profiling & tuning (memory, GPU sharing, caching); light mode; disk/retention policies; error→fix hints & help; security review (deps, input, paths, secrets); accessibility audit; full test sweep; user guide.
**Exit:** performance targets (08 §2) met; no high-severity findings.

### Phase 11 — Packaging & deployment
**Tasks:** local launcher + Windows installer (optional Tauri shell); Docker images (GPU/CPU), compose with Postgres/MinIO/Caddy; auth for server mode; backups; release pipeline, versioning, changelog.
**Exit:** clean install on a fresh Windows machine and a fresh Linux GPU server.

---

## Working agreement
1. One phase at a time; each starts with a short plan and ends with a demo.
2. Every feature lands with tests and its doc page.
3. You approve tech/UX decisions that change scope; ADRs record them.
4. I explain each component as we build it: what it does, why, and how it works.
