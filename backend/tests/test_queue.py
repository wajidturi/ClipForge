from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from clipforge.db.base import utcnow
from clipforge.db.enums import JobStatus
from clipforge.db.session import get_sessionmaker
from clipforge.jobs import queue

LEASE = 30


def test_enqueue_lease_complete(db: Session) -> None:
    job = queue.enqueue(db, "system.selftest", {"steps": 1})
    db.commit()
    leased = queue.lease(db, "w1", ["cpu"], LEASE)
    assert leased is not None and leased.id == job.id
    assert leased.status == JobStatus.running and leased.attempts == 1
    assert leased.lease_owner == "w1" and leased.lease_until > utcnow()
    done = queue.complete(db, job.id, {"ok": True})
    assert (
        done.status == JobStatus.succeeded and done.progress == 100 and done.result == {"ok": True}
    )
    assert queue.lease(db, "w1", ["cpu"], LEASE) is None


def test_lease_respects_caps_and_priority(db: Session) -> None:
    gpu = queue.enqueue(db, "t.gpu", caps=["gpu"], priority=1)
    low = queue.enqueue(db, "t.low", priority=200)
    high = queue.enqueue(db, "t.high", priority=10)
    db.commit()
    assert queue.lease(db, "cpu-worker", ["cpu"], LEASE).id == high.id  # gpu job skipped
    assert queue.lease(db, "cpu-worker", ["cpu"], LEASE).id == low.id
    assert queue.lease(db, "cpu-worker", ["cpu"], LEASE) is None
    assert queue.lease(db, "gpu-worker", ["cpu", "gpu"], LEASE).id == gpu.id


def test_only_one_worker_wins(db: Session) -> None:
    job = queue.enqueue(db, "t.race")
    db.commit()
    maker = get_sessionmaker()
    with maker() as s1, maker() as s2:
        a = queue.lease(s1, "w1", ["cpu"], LEASE)
        b = queue.lease(s2, "w2", ["cpu"], LEASE)
    assert [x.id for x in (a, b) if x] == [job.id]


def test_fail_retries_with_backoff_then_fails(db: Session) -> None:
    job = queue.enqueue(db, "t.flaky", max_attempts=2)
    db.commit()
    queue.lease(db, "w", ["cpu"], LEASE)
    j = queue.fail(db, job.id, "boom")
    assert j.status == JobStatus.queued and j.available_at > utcnow()
    assert queue.lease(db, "w", ["cpu"], LEASE) is None  # still backing off
    j.available_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert queue.lease(db, "w", ["cpu"], LEASE) is not None
    j = queue.fail(db, job.id, "boom again")
    assert j.status == JobStatus.failed and j.attempts == 2 and "boom again" in (j.error or "")


def test_permanent_failure_skips_retry(db: Session) -> None:
    job = queue.enqueue(db, "t.bad")
    db.commit()
    queue.lease(db, "w", ["cpu"], LEASE)
    assert queue.fail(db, job.id, "bad input", retryable=False).status == JobStatus.failed


def test_cancel_queued_and_running(db: Session) -> None:
    queued = queue.enqueue(db, "t.a")
    running = queue.enqueue(db, "t.b")
    db.commit()
    queue.lease(db, "w", ["cpu"], LEASE)  # leases t.a (older)
    queue.lease(db, "w", ["cpu"], LEASE)
    queued2 = queue.enqueue(db, "t.c")
    db.commit()
    assert queue.request_cancel(db, queued2.id).status == JobStatus.cancelled
    j = queue.request_cancel(db, running.id)
    assert j.status == JobStatus.running and j.cancel_requested
    assert queue.heartbeat(db, running.id, "w", LEASE) is True
    assert queue.is_cancel_requested(db, queued.id) is False


def test_retry_resets_failed_job(db: Session) -> None:
    job = queue.enqueue(db, "t.x", max_attempts=1)
    db.commit()
    queue.lease(db, "w", ["cpu"], LEASE)
    queue.fail(db, job.id, "nope")
    j = queue.retry(db, job.id)
    assert j.status == JobStatus.queued and j.attempts == 0 and j.error is None


def test_expired_lease_is_requeued(db: Session) -> None:
    job = queue.enqueue(db, "t.dead")
    db.commit()
    j = queue.lease(db, "dead-worker", ["cpu"], LEASE)
    j.lease_until = utcnow() - timedelta(seconds=1)
    db.commit()
    assert queue.requeue_expired(db) == 1
    db.refresh(j)
    assert j.status == JobStatus.queued and j.lease_owner is None
    assert queue.lease(db, "w2", ["cpu"], LEASE).id == job.id
