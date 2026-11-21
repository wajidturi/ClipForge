# 08 — Testing, Optimization, Deployment & Documentation

## 1. Testing & QA

| Level | Tool | Scope | Gate |
|---|---|---|---|
| Unit | pytest, hypothesis | pipeline pure functions: window scoring, sentence builder, EDL remap of caption times, ASS generation, heat score, spike detection, schedule planner, validators | ≥ 85 % coverage on `pipeline/` & `selection/` |
| Golden-media | pytest + small fixture clips (5–20 s, our own recordings/CC0) | reframe plan, render output: duration, resolution, LUFS (±0.5), caption frames via frame hash, QC verdicts | must match stored goldens |
| Integration | pytest + SQLite & Postgres (testcontainers) | API ↔ services ↔ jobs ↔ DB; job retry/lease/cancel; migrations up/down | every PR |
| Contract | OpenAPI diff + generated TS client compile | breaking API changes | every PR |
| AI | recorded responses (respx/VCR) for deterministic tests; **eval set** of ~50 labelled source windows to score selection quality (precision@N vs human picks) | prompt/model changes must not regress the eval |
| Frontend unit | Vitest + Testing Library | components, hooks, forms | every PR |
| E2E | Playwright | onboarding → create run (fixture source, mocked AI) → review → edit → re-render → schedule → export | nightly + release |
| Performance | pytest-benchmark, custom harness, locust (API) | render time per minute of output, transcription RTF, memory peak, API p95 | tracked per release |
| Static | ruff, mypy (strict on core), eslint, tsc, bandit, pip-audit, pnpm audit | | every PR |

Manual QA checklist per release: Windows + macOS + Linux, GPU + CPU, light mode, each layout/format/style rendered once and eyeballed via contact sheet.

## 2. Optimization

| Concern | Measures |
|---|---|
| Memory | stream audio/frames (PyAV generators), never load whole video; analyse on 360p proxies; Whisper chunking; per-worker RSS guard + light mode |
| GPU | single shared Whisper model per GPU worker (lazy-loaded, kept warm); VRAM budget → max concurrent GPU jobs; NVENC for encode; decode with `-hwaccel cuda` where it helps |
| CPU | process pool sized to cores; FFmpeg threads tuned; vision sampling at low fps; numpy vectorisation |
| Speed | download only needed sections; content-hash caching of every step; one FFmpeg pass per render; parallel renders (default 3, auto by RAM/VRAM) |
| Large files | windowing for long streams; resumable downloads; disk-space guard; retention cleanup |
| Concurrency | DB-level leases, idempotent steps, per-source locks, backpressure (queue limits) |
| AI cost/latency | prompt caching of stable system prompt; candidates instead of full transcripts by default; batch API for autopilot; token/cost logged per run |
| Scalability | stateless API; workers scale horizontally (server mode); object storage; Postgres; Redis bus optional |

Targets (RTX 4050-class laptop): transcription ≥ 15× realtime (GPU, `small`); one 45 s Short rendered < 90 s; 10-Short run from a 1 h source < 25 min end-to-end; API p95 < 150 ms.

## 3. Deployment

**Local (primary):**
- `clipforge` launcher (Python entry point) starts api + workers + scheduler, opens browser at `http://127.0.0.1:<port>/?t=<token>`.
- First-run `doctor` checks ffmpeg, GPU, disk, downloads models on demand.
- Windows installer (Phase 11): bundled Python via uv-managed env or PyInstaller one-dir + optional Tauri shell; auto-update through signed GitHub/GitLab releases only.

**Server / self-hosted:**
- Docker images: `api` (slim), `worker-gpu` (CUDA 12 runtime + cuDNN 9 + ffmpeg w/ NVENC), `worker-cpu`, `frontend` built into api static.
- docker-compose: api, worker-gpu, worker-cpu, scheduler, postgres, (redis optional), minio (optional S3), caddy (TLS reverse proxy).
- Config via env vars (03 §3); secrets via Docker secrets/env, never in images.
- Storage: volume or S3; DB backups scheduled; health checks; log shipping (JSON).
- Security: HTTPS only, auth required, CORS locked, rate limits on auth, CSP headers, non-root containers, dependency scanning in CI, image signing.
- CI/CD: lint → tests → build images → push → deploy (tag-based); DB migrations run as a pre-deploy job.

## 4. Documentation (maintained throughout)

| Doc | Content | When |
|---|---|---|
| `README.md` | what it is, quick start | Phase 1, kept current |
| `docs/setup.md` | dev environment, per-OS steps, troubleshooting | Phase 1 |
| `docs/architecture.md` (+ diagrams) | from 04, kept in sync | each phase |
| `docs/adr/NNN-*.md` | one decision per file | when decided |
| `docs/api.md` | generated OpenAPI + examples | auto |
| `docs/pipeline/*.md` | one page per engine (ingest, transcription, signals, selection, reframe, captions, formats, audio fx, qc, live) with parameters | as built |
| `docs/dependencies.md` | locked versions + licenses (auto-generated) | each release |
| `docs/user-guide/` | end-user how-tos | Phase 10 |
| `CHANGELOG.md` | per release | each release |
