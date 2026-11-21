# ADR 0001 — Local-first web app: FastAPI + React, SQLite/PostgreSQL

**Status:** accepted (Phase 1) · **Date:** 2026-11-21

## Context
The app does heavy local media work (FFmpeg, Whisper, MediaPipe) and must run on a single
Windows PC without extra services, yet be deployable as a hosted service later.

## Decision
- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, structlog. Package `clipforge` in `backend/src`.
- Frontend: React 19 + TypeScript 7 + Vite 8, Tailwind CSS 4, TanStack Query, Zustand, react-router, i18next.
- One schema for SQLite (local, WAL mode) and PostgreSQL (server). UUIDv7 primary keys, JSON→JSONB on Postgres,
  timezone-aware UTC timestamps enforced by a `UTCDateTime` type (SQLite drops tzinfo).
- The full schema from `05-database-design.md` (29 tables) is created in migration `0001`, so later phases add behaviour, not structure.
- The API serves the built SPA in production; during development Vite proxies `/api` (incl. WebSocket) to the API.

## Consequences
- Zero-install database locally; real concurrency in server mode.
- Python 3.12 is pinned (`>=3.12,<3.13`) because MediaPipe/CTranslate2 wheels lag new Python releases.
- Windows path-length limit requires the project in a short path (documented in setup.md).
