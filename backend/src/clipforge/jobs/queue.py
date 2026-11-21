"""Persistent job queue on top of the `jobs` table.

Why a DB queue: the desktop app must not require Redis; jobs survive restarts;
every state change is queryable for the UI. Claiming is an atomic
`UPDATE ... WHERE status='queued'` so it is safe with several worker processes on
SQLite and PostgreSQL alike (see docs/adr/0002-db-backed-job-queue.md).

Lifecycle:  queued -> running -> succeeded | failed | cancelled
            running --(error, attempts left)--> queued (delayed by backoff)
            running --(lease expired: worker died)--> queued
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from clipforge.db.base import utcnow
from clipforge.db.enums import JobStatus
from clipforge.db.models import Job

MAX_BACKOFF_S = 300


class JobNotFoundError(LookupError):
    pass


class InvalidJobStateError(ValueError):
    pass


def backoff_seconds(attempts: int) -> int:
    return int(min(MAX_BACKOFF_S, 2 ** max(attempts, 1)))


def enqueue(
    session: Session,
    type_: str,
    payload: dict[str, Any] | None = None,
    *,
    label: str | None = None,
    caps: Iterable[str] = ("cpu",),
    priority: int = 100,
    parent_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    max_attempts: int = 3,
    cache_key: str | None = None,
    subject: tuple[str, uuid.UUID] | None = None,
) -> Job:
    job = Job(
        type=type_,
        label=label,
        subject_type=subject[0] if subject else None,
        subject_id=subject[1] if subject else None,
        payload=payload or {},
        required_caps=sorted(set(caps)),
        priority=priority,
        parent_id=parent_id,
        run_id=run_id,
        max_attempts=max_attempts,
        cache_key=cache_key,
        status=JobStatus.queued,
    )
    session.add(job)
    session.flush()
    return job


def get(session: Session, job_id: uuid.UUID) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise JobNotFoundError(str(job_id))
    return job


def lease(session: Session, worker_id: str, caps: Sequence[str], lease_seconds: int) -> Job | None:
    """Claim the next runnable job this worker can handle, or return None."""
    now = utcnow()
    have = set(caps)
    rows = session.scalars(
        select(Job)
        .where(Job.status == JobStatus.queued, Job.cancel_requested.is_(False))
        .where(or_(Job.available_at.is_(None), Job.available_at <= now))
        .order_by(Job.priority, Job.created_at)
        .limit(25)
    ).all()
    for job in rows:
        if not set(job.required_caps or []) <= have:
            continue
        claimed = session.execute(
            update(Job)
            .where(Job.id == job.id, Job.status == JobStatus.queued)
            .values(
                status=JobStatus.running,
                lease_owner=worker_id,
                lease_until=now + timedelta(seconds=lease_seconds),
                heartbeat_at=now,
                started_at=now,
                attempts=Job.attempts + 1,
                error=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount == 1:  # type: ignore[attr-defined]
            session.commit()
            session.refresh(job)
            return job
        session.rollback()  # another worker won the race; try the next one
    return None


def heartbeat(session: Session, job_id: uuid.UUID, worker_id: str, lease_seconds: int) -> bool:
    """Extend the lease. Returns True when cancellation was requested."""
    now = utcnow()
    session.execute(
        update(Job)
        .where(Job.id == job_id, Job.lease_owner == worker_id, Job.status == JobStatus.running)
        .values(lease_until=now + timedelta(seconds=lease_seconds), heartbeat_at=now)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    cancel = session.scalar(select(Job.cancel_requested).where(Job.id == job_id))
    return bool(cancel)


def is_cancel_requested(session: Session, job_id: uuid.UUID) -> bool:
    return bool(session.scalar(select(Job.cancel_requested).where(Job.id == job_id)))


def report_progress(
    session: Session, job_id: uuid.UUID, progress: float | None, step: str | None = None
) -> None:
    values: dict[str, Any] = {"updated_at": utcnow()}
    if progress is not None:
        values["progress"] = max(0.0, min(100.0, progress))
    if step is not None:
        values["step"] = step[:200]
    session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    session.commit()


def _finish(job: Job, status: JobStatus) -> None:
    job.status = status
    job.finished_at = utcnow()
    job.lease_owner = None
    job.lease_until = None


def complete(session: Session, job_id: uuid.UUID, result: dict[str, Any] | None = None) -> Job:
    job = get(session, job_id)
    job.result = result or {}
    job.progress = 100.0
    _finish(job, JobStatus.succeeded)
    session.commit()
    return job


def fail(session: Session, job_id: uuid.UUID, error: str, *, retryable: bool = True) -> Job:
    job = get(session, job_id)
    job.error = error[-4000:]
    if retryable and job.attempts < job.max_attempts and not job.cancel_requested:
        job.status = JobStatus.queued
        job.available_at = utcnow() + timedelta(seconds=backoff_seconds(job.attempts))
        job.lease_owner = None
        job.lease_until = None
        job.step = f"retrying (attempt {job.attempts + 1} of {job.max_attempts})"
    else:
        _finish(job, JobStatus.failed)
    session.commit()
    return job


def mark_cancelled(session: Session, job_id: uuid.UUID) -> Job:
    job = get(session, job_id)
    _finish(job, JobStatus.cancelled)
    job.step = "cancelled"
    session.commit()
    return job


def request_cancel(session: Session, job_id: uuid.UUID) -> Job:
    job = get(session, job_id)
    if job.status.is_final:
        raise InvalidJobStateError(f"job is already {job.status.value}")
    job.cancel_requested = True
    if job.status == JobStatus.queued:
        _finish(job, JobStatus.cancelled)
        job.step = "cancelled"
    session.commit()
    return job


def retry(session: Session, job_id: uuid.UUID) -> Job:
    job = get(session, job_id)
    if job.status not in (JobStatus.failed, JobStatus.cancelled):
        raise InvalidJobStateError(
            f"only failed or cancelled jobs can be retried, not {job.status}"
        )
    job.status = JobStatus.queued
    job.attempts = 0
    job.cancel_requested = False
    job.available_at = None
    job.finished_at = None
    job.error = None
    job.progress = 0.0
    job.step = None
    session.commit()
    return job


def requeue_expired(session: Session) -> int:
    """Return jobs whose worker stopped heart-beating to the queue (or fail them)."""
    now = utcnow()
    expired = session.scalars(
        select(Job).where(Job.status == JobStatus.running, Job.lease_until < now)
    ).all()
    for job in expired:
        if job.cancel_requested:
            _finish(job, JobStatus.cancelled)
        elif job.attempts < job.max_attempts:
            job.status = JobStatus.queued
            job.lease_owner = None
            job.lease_until = None
            job.step = "requeued after worker stopped responding"
        else:
            job.error = "worker stopped responding"
            _finish(job, JobStatus.failed)
    session.commit()
    return len(expired)
