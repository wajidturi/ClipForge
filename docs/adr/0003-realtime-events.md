# ADR 0003 — Real-time UI updates over WebSocket (DB change polling in the API)

**Status:** accepted (Phase 1) · **Date:** 2026-11-21

## Context
Workers are separate processes that only write to the database. The UI should show progress instantly
without each browser tab polling the API.

## Decision
- The API runs one `EventHub` task that queries `jobs WHERE updated_at > cursor` every 0.5 s (only while at
  least one browser is connected) and pushes `{"type": "job.updated", "job": {...}}` to every WebSocket at `/api/v1/ws`.
- Heartbeats do not touch `updated_at`, so idle running jobs create no events; progress, status and result changes do.
- The browser keeps one WebSocket, patches React Query's cache (`mergeJob`, which ignores out-of-order older
  events), reconnects with exponential backoff and refetches after a reconnect to catch missed events.
- A 15 s `ping` frame keeps idle connections alive through proxies.

## Alternatives considered
PostgreSQL `LISTEN/NOTIFY` (not available on SQLite; planned as a drop-in for server mode), Redis pub/sub (extra service), browser polling (N tabs × N endpoints).

## Consequences
One cheap indexed query per 0.5 s regardless of the number of tabs. Latency ≤ 0.5 s, fine for progress bars.
