# ClipForge (working name)

A local-first, AI-assisted application that turns long videos and live streams into finished vertical Shorts: it finds the best moments, reframes to 9:16 with face tracking, adds animated captions and hooks, checks quality, and lets you review, edit, schedule and publish.

**Status:** Phase 6 MVP + gaming templates: five templates (Streamer First, Gameplay First, Dual Vision, Floating Facecam, Cinematic Gaming), one-click Create → generate, and a post-render customisation studio with live preview (logo, text, emojis, stickers, captions, effects, undo/redo) that re-renders in seconds. See [docs/pipeline/templates.md](docs/pipeline/templates.md). Next: Playwright E2E, then Phase 7 (creators, discovery, live).

## Quick start (Windows)

```powershell
.\scripts\setup.ps1   # once: checks tools, installs Python 3.12 + packages, npm packages
.\scripts\dev.ps1     # API + 2 workers, and the web app at http://localhost:5173
```

Details, manual commands and troubleshooting: [docs/setup.md](docs/setup.md).

## Repository layout

```
backend/            Python package `clipforge` (FastAPI API, job queue, workers, CLI)
  src/clipforge/
    api/            HTTP routes, WebSocket, schemas, event hub
    core/           config, logging, ids, data paths, system profile / doctor
    db/             SQLAlchemy models (29 tables), enums, session, migration helpers
    jobs/           queue (leases, retries, cancel), worker, handler registry, handlers/
    cli.py          `clipforge dev | api | worker | doctor | db | openapi`
  migrations/       Alembic migrations
  tests/            pytest
frontend/           React 19 + TypeScript + Vite + Tailwind
  src/app/          shell + navigation
  src/pages/        screens (Dashboard; the rest arrive phase by phase)
  src/components/   UI primitives, JobRow
  src/lib/          typed API client (generated), jobs/query helpers, WebSocket events, i18n, theme
docs/               planning documents, setup guide, ADRs
scripts/            setup.ps1, dev.ps1, dev.sh
.github/workflows/  CI
```

## Documentation

| # | Document |
|---|---|
| — | [Developer setup](docs/setup.md) |
| — | Pipeline: [ingestion](docs/pipeline/ingest.md) · [transcription & signals](docs/pipeline/analysis.md) · [moment selection](docs/pipeline/selection.md) · [rendering & QC](docs/pipeline/render.md) · [studio, review & export](docs/pipeline/studio.md) · [templates & customisation](docs/pipeline/templates.md) |
| 01 | [Reverse engineering & research findings](docs/01-research-findings.md) |
| 02 | [Feature inventory](docs/02-feature-inventory.md) |
| 03 | [Technology stack, environment & dependencies](docs/03-tech-stack-and-environment.md) |
| 04 | [Architecture & system design (incl. API)](docs/04-architecture.md) |
| 05 | [Database design](docs/05-database-design.md) |
| 06 | [Frontend plan (UI/UX)](docs/06-frontend-plan.md) |
| 07 | [Backend, AI & video processing plan](docs/07-backend-ai-video-plan.md) |
| 08 | [Testing, optimization, deployment & documentation](docs/08-quality-performance-deployment.md) |
| 09 | [Phase-by-phase roadmap](docs/09-roadmap.md) |
| ADR | [0001 stack](docs/adr/0001-architecture-and-stack.md) · [0002 job queue](docs/adr/0002-db-backed-job-queue.md) · [0003 real-time events](docs/adr/0003-realtime-events.md) · [0004 tooling](docs/adr/0004-tooling.md) · [0005 AI providers](docs/adr/0005-ai-providers.md) |
