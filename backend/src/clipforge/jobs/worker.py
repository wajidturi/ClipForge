"""Worker process: leases jobs it is capable of, runs them, keeps the lease alive.

Each worker declares capabilities (cpu, gpu, net, live). GPU-heavy jobs will only be
picked by workers started with `--caps gpu`, which keeps VRAM use under control.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import traceback
import uuid
from collections.abc import Sequence
from typing import Any

from clipforge.core.config import Settings, get_settings
from clipforge.core.logging import get_logger
from clipforge.db.session import get_sessionmaker
from clipforge.jobs import queue
from clipforge.jobs.registry import JobCancelledError, JobContext, PermanentJobError, get_spec

log = get_logger(__name__)


class Worker:
    def __init__(
        self,
        worker_id: str | None = None,
        caps: Sequence[str] = ("cpu", "net"),
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.caps = tuple(caps)
        self.stop = threading.Event()
        self.sessions = get_sessionmaker()
        self._last_requeue = 0.0

    # ------------------------------------------------------------------ loop
    def run_forever(self) -> None:
        log.info("worker.start", worker=self.id, caps=self.caps)
        while not self.stop.is_set():
            if not self.run_once():
                self.stop.wait(self.settings.job_poll_interval)
        log.info("worker.stop", worker=self.id)

    def run_once(self) -> bool:
        """Lease and run at most one job. Returns True if a job ran."""
        with self.sessions() as s:
            if time.monotonic() - self._last_requeue > 10:
                self._last_requeue = time.monotonic()
                if n := queue.requeue_expired(s):
                    log.warning("worker.requeued_expired", count=n)
            job = queue.lease(s, self.id, self.caps, self.settings.job_lease_seconds)
            if job is None:
                return False
            job_id, job_type, payload = job.id, job.type, dict(job.payload)
            attempt, max_attempts = job.attempts, job.max_attempts
        self._execute(job_id, job_type, payload, attempt, max_attempts)
        return True

    # ------------------------------------------------------------------ one job
    def _execute(
        self,
        job_id: uuid.UUID,
        job_type: str,
        payload: dict[str, Any],
        attempt: int,
        max_attempts: int = 1,
    ) -> None:
        jlog = log.bind(job_id=str(job_id), type=job_type, attempt=attempt)
        spec = get_spec(job_type)
        if spec is None:
            with self.sessions() as s:
                queue.fail(s, job_id, f"no handler for job type '{job_type}'", retryable=False)
            jlog.error("job.unknown_type")
            return

        def progress(pct: float | None, step: str | None) -> None:
            with self.sessions() as s:
                queue.report_progress(s, job_id, pct, step)

        ctx = JobContext(
            job_id, attempt, self.settings.resolved_data_dir, progress, max_attempts=max_attempts
        )
        beat_stop = threading.Event()
        beat = threading.Thread(
            target=self._heartbeat, args=(job_id, ctx, beat_stop), daemon=True, name="heartbeat"
        )
        beat.start()
        jlog.info("job.start")
        started = time.monotonic()
        try:
            result = spec.handler(ctx, payload)
        except JobCancelledError:
            with self.sessions() as s:
                queue.mark_cancelled(s, job_id)
            jlog.info("job.cancelled")
        except PermanentJobError as e:
            with self.sessions() as s:
                queue.fail(s, job_id, str(e), retryable=False)
            jlog.warning("job.failed_permanent", error=str(e))
        except Exception as e:
            with self.sessions() as s:
                job = queue.fail(s, job_id, f"{e}\n{traceback.format_exc()}")
            jlog.warning("job.failed", error=str(e), will_retry=job.status == "queued")
        else:
            with self.sessions() as s:
                queue.complete(s, job_id, result)
            jlog.info("job.done", seconds=round(time.monotonic() - started, 2))
        finally:
            beat_stop.set()
            beat.join(timeout=5)

    def _heartbeat(self, job_id: uuid.UUID, ctx: JobContext, stop: threading.Event) -> None:
        """Every second: notice cancel requests. Every lease/3 seconds: extend the lease."""
        extend_every = max(1.0, self.settings.job_lease_seconds / 3)
        last_extend = time.monotonic()
        while not stop.wait(1.0):
            try:
                with self.sessions() as s:
                    if time.monotonic() - last_extend >= extend_every:
                        last_extend = time.monotonic()
                        cancel = queue.heartbeat(
                            s, job_id, self.id, self.settings.job_lease_seconds
                        )
                    else:
                        cancel = queue.is_cancel_requested(s, job_id)
                if cancel:
                    ctx.request_cancel()
            except Exception as e:
                log.warning("worker.heartbeat_error", error=str(e))
