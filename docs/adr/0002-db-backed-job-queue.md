# ADR 0002 — Database-backed job queue with leases

**Status:** accepted (Phase 1) · **Date:** 2026-11-21

## Context
Every heavy step (download, transcribe, render) runs in the background and must survive app restarts,
support cancel/retry, report progress, and run in several worker processes (CPU vs GPU). The reference tool
kept jobs in an in-memory dict, so a restart lost everything.

## Decision
Jobs live in the `jobs` table. Workers claim work with an atomic conditional update:
`UPDATE jobs SET status='running', lease_owner=?, lease_until=now+60s WHERE id=? AND status='queued'`.
Only the worker whose update changes one row wins, which is safe on SQLite and PostgreSQL alike.

- **Capabilities:** each job lists `required_caps` (`cpu`, `gpu`, `net`, `live`); a worker only takes jobs whose caps it has. GPU jobs therefore run only on GPU workers, which bounds VRAM use.
- **Heartbeat:** while a job runs, a thread checks for cancel requests every second and extends the lease every `lease/3` seconds.
- **Crash recovery:** jobs whose lease expired (worker died) are re-queued, or failed when attempts are used up.
- **Retries:** failures retry with exponential backoff (2, 4, 8 … max 300 s) up to `max_attempts`; `PermanentJobError` skips retries.
- **Stop (cancel):** queued jobs cancel immediately, and so do the jobs a stopped job started (`parent_id`; a run's renders). A running job gets `cancel_requested`; within a second its worker ends every program the job started (FFmpeg, yt-dlp, Deno — child processes newer than the job, via psutil) and the handler stops at the next `ctx.check_cancelled()` / `ctx.sleep()`. If it has not returned after `CF_CANCEL_GRACE_S` (5 s) — e.g. stuck inside a C library — the worker records the job as cancelled ("stopped (worker restarted)") and exits with code 75; `clipforge dev` starts a fresh worker. A stopped job never ends as *failed*.
- **Cleanup hooks:** `@job_handler(..., on_cancel=fn)` puts the job's subject back in order after a stop (a Short leaves "rendering", a source/run is marked cancelled), also for jobs stopped while queued. A sweep (`services/repair.py`, at API start and every 10 s in workers) frees anything left "rendering" / "downloading" / "analyzing" / "running" with no queued or running job.
- **Stop all / history:** `POST /jobs/cancel-all` stops every queued and running job; `DELETE /jobs/history` deletes finished jobs (succeeded, failed, cancelled).
- **Handlers** register with `@job_handler("type", caps=..., public=...)`; only `public` types can be started via `POST /api/v1/jobs`.

## Alternatives considered
Celery/RQ/arq (need Redis — an extra service on every desktop), Dramatiq (same), in-process threads (no crash recovery).

## Consequences
No extra infrastructure. Throughput is limited by DB writes (fine for tens of concurrent jobs). The queue
API is small, so a Redis-backed implementation can replace it for large server deployments.
