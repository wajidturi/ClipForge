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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from clipforge.core.config import Settings, get_settings
from clipforge.core.logging import get_logger
from clipforge.db.session import get_sessionmaker
from clipforge.jobs import procs, queue
from clipforge.jobs.registry import (
    JobCancelledError,
    JobContext,
    JobSpec,
    PermanentJobError,
    get_spec,
)
from clipforge.services.repair import repair_orphans

log = get_logger(__name__)


class Worker:
    def __init__(
        self,
        worker_id: str | None = None,
        caps: Sequence[str] = ("cpu", "net"),
        settings: Settings | None = None,
        hard_exit: Callable[[int], None] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.caps = tuple(caps)
        self.stop = threading.Event()
        self.sessions = get_sessionmaker()
        self._last_requeue = 0.0
        # How a stuck, stopped job is ended: the whole process exits (tests swap it).
        self.hard_exit = hard_exit or os._exit

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
                repair_orphans(s)
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
        run = _Running(job_id, spec, payload, ctx, since=time.time())
        beat_stop = threading.Event()
        beat = threading.Thread(
            target=self._heartbeat, args=(run, beat_stop), daemon=True, name="heartbeat"
        )
        beat.start()
        jlog.info("job.start")
        started = time.monotonic()
        result: dict[str, Any] | None = None
        error: BaseException | None = None
        try:
            result = spec.handler(ctx, payload)
        except Exception as e:
            error = e
        finally:
            with run.lock:
                run.done = True
            beat_stop.set()
            beat.join(timeout=5)
        if run.killed:  # only in tests: a real worker process has already exited
            return
        if ctx.cancelled or isinstance(error, JobCancelledError):
            # Whatever the handler raised, a stopped job ends as cancelled, not failed.
            self._cancelled(run)
            jlog.info("job.cancelled")
        elif isinstance(error, PermanentJobError):
            with self.sessions() as s:
                queue.fail(s, job_id, str(error), retryable=False)
            jlog.warning("job.failed_permanent", error=str(error))
        elif error is not None:
            tb = "".join(traceback.format_exception(error))
            with self.sessions() as s:
                job = queue.fail(s, job_id, f"{error}\n{tb}")
            jlog.warning("job.failed", error=str(error), will_retry=job.status == "queued")
        else:
            with self.sessions() as s:
                queue.complete(s, job_id, result)
            jlog.info("job.done", seconds=round(time.monotonic() - started, 2))

    def _cancelled(self, run: _Running, step: str = "cancelled") -> None:
        if run.spec.on_cancel is not None:
            try:
                run.spec.on_cancel(run.payload)
            except Exception as e:
                log.warning("job.on_cancel_error", job_id=str(run.job_id), error=str(e))
        with self.sessions() as s:
            queue.mark_cancelled(s, run.job_id, step)

    def _heartbeat(self, run: _Running, stop: threading.Event) -> None:
        """Every second: notice a stop request. Every lease/3 seconds: extend the lease.

        On a stop: end the programs the job started at once (FFmpeg, downloads), then
        give the handler `cancel_grace_s` to return. If it is stuck in code that cannot
        be interrupted (transcription, picture analysis...), end this whole worker
        process: the job is recorded as cancelled and the supervisor starts a new worker.
        """
        extend_every = max(1.0, self.settings.job_lease_seconds / 3)
        last_extend = time.monotonic()
        cancel_at: float | None = None
        while not stop.wait(1.0):
            try:
                if cancel_at is None:
                    with self.sessions() as s:
                        if time.monotonic() - last_extend >= extend_every:
                            last_extend = time.monotonic()
                            cancel = queue.heartbeat(
                                s, run.job_id, self.id, self.settings.job_lease_seconds
                            )
                        else:
                            cancel = queue.is_cancel_requested(s, run.job_id)
                    if cancel:
                        cancel_at = time.monotonic()
                        run.ctx.request_cancel()
                        procs.kill_job_children(run.since)
                elif time.monotonic() - cancel_at >= self.settings.cancel_grace_s:
                    with run.lock:
                        if run.done:
                            return
                        run.killed = True
                        self._kill(run)
                    return
            except Exception as e:
                log.warning("worker.heartbeat_error", error=str(e))

    def _kill(self, run: _Running) -> None:
        log.warning("job.killed", job_id=str(run.job_id), worker=self.id)
        procs.kill_job_children(run.since)
        self._cancelled(run, "stopped (worker restarted)")
        self.hard_exit(EXIT_JOB_KILLED)


EXIT_JOB_KILLED = 75  # the supervisor restarts a worker that exits with any code


@dataclass
class _Running:
    job_id: uuid.UUID
    spec: JobSpec
    payload: dict[str, Any]
    ctx: JobContext
    since: float  # time.time() when the job started: its child processes are newer
    lock: threading.Lock = field(default_factory=threading.Lock)
    done: bool = False
    killed: bool = False
