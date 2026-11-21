from __future__ import annotations

import threading
import time

from sqlalchemy.orm import Session

from clipforge.db.enums import JobStatus
from clipforge.jobs import queue
from clipforge.jobs.worker import Worker


def _wait(db: Session, job_id, status: JobStatus, timeout: float = 10) -> None:  # type: ignore[no-untyped-def]
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        db.expire_all()
        if queue.get(db, job_id).status == status:
            return
        time.sleep(0.05)
    raise AssertionError(f"job never reached {status}: {queue.get(db, job_id).status}")


def test_selftest_runs_to_completion(db: Session) -> None:
    job = queue.enqueue(db, "system.selftest", {"steps": 3, "delay": 0})
    db.commit()
    assert Worker("t1").run_once() is True
    db.expire_all()
    j = queue.get(db, job.id)
    assert j.status == JobStatus.succeeded and j.progress == 100 and j.step == "step 3 of 3"
    assert j.result == {"steps": 3, "attempt": 1}


def test_failure_then_retry_succeeds(db: Session) -> None:
    job = queue.enqueue(db, "system.selftest", {"steps": 3, "delay": 0, "fail_at": 2})
    db.commit()
    Worker("t1").run_once()
    db.expire_all()
    j = queue.get(db, job.id)
    assert j.status == JobStatus.queued and "simulated failure" in (j.error or "")
    j.available_at = None  # skip backoff in the test
    db.commit()
    Worker("t1").run_once()
    db.expire_all()
    assert queue.get(db, job.id).status == JobStatus.succeeded


def test_unknown_type_fails_permanently(db: Session) -> None:
    job = queue.enqueue(db, "does.not.exist")
    db.commit()
    Worker("t1").run_once()
    db.expire_all()
    j = queue.get(db, job.id)
    assert j.status == JobStatus.failed and "no handler" in (j.error or "")


def test_bad_payload_is_permanent(db: Session) -> None:
    job = queue.enqueue(db, "system.selftest", {"steps": 0})
    db.commit()
    Worker("t1").run_once()
    db.expire_all()
    assert queue.get(db, job.id).attempts == 1
    assert queue.get(db, job.id).status == JobStatus.failed


def test_cancel_running_job(db: Session) -> None:
    job = queue.enqueue(db, "system.selftest", {"steps": 100, "delay": 0.1})
    db.commit()
    w = Worker("t1")
    t = threading.Thread(target=w.run_once)
    t.start()
    _wait(db, job.id, JobStatus.running)
    queue.request_cancel(db, job.id)
    t.join(timeout=10)
    assert not t.is_alive()
    db.expire_all()
    j = queue.get(db, job.id)
    assert j.status == JobStatus.cancelled and j.progress < 100
