"""Job controls: a stopped job really ends (with every program it started), Stop all,
Clear history, and permanent delete of Shorts (files and records)."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psutil
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from clipforge.api.app import create_app
from clipforge.core.config import Settings, get_settings
from clipforge.db.enums import (
    AssetKind,
    AssetOwner,
    JobStatus,
    Platform,
    QcVerdict,
    ShortStatus,
    SourceStatus,
    VersionOrigin,
    VersionStatus,
)
from clipforge.db.models import (
    Job,
    MediaAsset,
    QcReport,
    Short,
    ShortPart,
    ShortVersion,
    Source,
)
from clipforge.db.session import get_sessionmaker
from clipforge.jobs import queue
from clipforge.jobs.registry import JobContext, job_handler
from clipforge.jobs.worker import EXIT_JOB_KILLED, Worker

SLEEPER = [sys.executable, "-c", "import time; time.sleep(120)"]
STATE: dict[str, Any] = {}


def _on_cancel(payload: dict[str, Any]) -> None:
    STATE.setdefault("on_cancel", []).append(payload)


@job_handler("test.stubborn", on_cancel=_on_cancel)
def stubborn(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Starts a long program, then is stuck in work that never checks for a stop
    (like transcription inside a C library)."""
    STATE["pid"] = subprocess.Popen(SLEEPER).pid
    STATE["started"].set()
    STATE["released"].wait(30)  # a real worker process is gone long before this
    return {}


@job_handler("test.polite", on_cancel=_on_cancel)
def polite(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Starts a program and waits for it, checking for a stop like FFmpeg steps do."""
    proc = subprocess.Popen(SLEEPER)
    STATE["pid"] = proc.pid
    STATE["started"].set()
    while proc.poll() is None:
        ctx.sleep(0.1)
    raise RuntimeError("the program died")  # what a killed FFmpeg looks like


@pytest.fixture(autouse=True)
def fresh_state() -> Iterator[None]:
    STATE.clear()
    STATE["started"] = threading.Event()
    STATE["released"] = threading.Event()
    yield
    STATE["released"].set()


def _wait_for(cond: Any, timeout: float = 15) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("condition never became true")


def _gone(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def _status(job_id: uuid.UUID) -> tuple[JobStatus, str | None]:
    with get_sessionmaker()() as s:
        j = queue.get(s, job_id)
        return j.status, j.step


def _start(db: Session, type_: str, worker: Worker) -> tuple[uuid.UUID, threading.Thread]:
    job = queue.enqueue(db, type_, {"x": 1})
    db.commit()
    t = threading.Thread(target=worker.run_once, daemon=True)
    t.start()
    assert STATE["started"].wait(15)
    return job.id, t


# ------------------------------------------------------------------ stopping
def test_stuck_job_is_ended_with_its_programs_and_the_worker_exits(db: Session) -> None:
    exits: list[int] = []

    def fake_exit(code: int) -> None:  # a real worker process ends here
        exits.append(code)
        STATE["released"].set()

    w = Worker("t1", settings=Settings(cancel_grace_s=1.0), hard_exit=fake_exit)
    job_id, t = _start(db, "test.stubborn", w)
    pid = STATE["pid"]
    assert not _gone(pid)
    queue.request_cancel(db, job_id)
    _wait_for(lambda: _gone(pid), 10)  # the program ends at once, not after the grace
    _wait_for(lambda: exits == [EXIT_JOB_KILLED], 10)
    t.join(10)
    assert _status(job_id) == (JobStatus.cancelled, "stopped (worker restarted)")
    assert STATE["on_cancel"] == [{"x": 1}]  # the subject is put back in order


def test_polite_job_ends_quickly_as_cancelled_not_failed(db: Session) -> None:
    exits: list[int] = []
    w = Worker("t1", settings=Settings(cancel_grace_s=5.0), hard_exit=exits.append)
    job_id, t = _start(db, "test.polite", w)
    pid = STATE["pid"]
    started = time.monotonic()
    queue.request_cancel(db, job_id)
    t.join(10)
    assert not t.is_alive() and time.monotonic() - started < 5
    assert _gone(pid)
    assert exits == []  # no forced exit needed
    status, _ = _status(job_id)
    assert status == JobStatus.cancelled
    assert STATE["on_cancel"] == [{"x": 1}]


def test_stopping_a_job_stops_the_jobs_it_started(db: Session) -> None:
    parent = queue.enqueue(db, "system.selftest")
    child = queue.enqueue(db, "system.selftest", parent_id=parent.id)
    grandchild = queue.enqueue(db, "system.selftest", parent_id=child.id)
    other = queue.enqueue(db, "system.selftest")
    db.commit()
    queue.request_cancel(db, parent.id)
    db.expire_all()
    for j in (parent, child, grandchild):
        assert queue.get(db, j.id).status == JobStatus.cancelled
    assert queue.get(db, other.id).status == JobStatus.queued


def test_error_after_a_stop_counts_as_cancelled(db: Session) -> None:
    job = queue.enqueue(db, "system.selftest")
    db.commit()
    queue.lease(db, "w", ("cpu",), 60)
    queue.request_cancel(db, job.id)
    queue.fail(db, job.id, "ffmpeg exited with code 1")
    db.expire_all()
    assert queue.get(db, job.id).status == JobStatus.cancelled


# ------------------------------------------------------------------ API
@pytest.fixture
def client(migrated: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def test_stop_all_and_clear_history(client: TestClient, db: Session) -> None:
    done = queue.enqueue(db, "system.selftest")
    failed = queue.enqueue(db, "system.selftest")
    queued = queue.enqueue(db, "system.selftest")
    running = queue.enqueue(db, "system.selftest")
    db.commit()
    queue.complete(db, done.id)
    queue.fail(db, failed.id, "x", retryable=False)
    running.status = JobStatus.running
    db.commit()

    r = client.post("/api/v1/jobs/cancel-all")
    assert r.status_code == 200 and r.json() == {"count": 2}
    db.expire_all()
    assert queue.get(db, queued.id).status == JobStatus.cancelled
    j = queue.get(db, running.id)
    assert j.status == JobStatus.running and j.cancel_requested  # its worker ends it

    r = client.delete("/api/v1/jobs/history")
    assert r.status_code == 200 and r.json() == {"count": 3}  # done, failed, cancelled
    left = client.get("/api/v1/jobs").json()["items"]
    assert [x["id"] for x in left] == [str(running.id)]


# ------------------------------------------------------------------ permanent delete
def _seed_short(db: Session) -> tuple[uuid.UUID, Path, Path]:
    src = Source(
        platform=Platform.youtube,
        external_id=uuid.uuid4().hex[:11],
        url="https://youtu.be/abcdefghijk",
        title="Stream",
        status=SourceStatus.ready,
        duration_s=600,
    )
    db.add(src)
    db.flush()
    short = Short(source_id=src.id, status=ShortStatus.review, hook="NO WAY")
    db.add(short)
    db.flush()
    db.add(ShortPart(short_id=short.id, idx=0, start_s=10, end_s=40))
    v = ShortVersion(
        short_id=short.id, version_no=1, origin=VersionOrigin.render, status=VersionStatus.ready
    )
    db.add(v)
    db.flush()
    db.add(QcReport(short_version_id=v.id, verdict=QcVerdict.pass_))
    short.active_version_id = v.id
    data = get_settings().resolved_data_dir
    video = data / "renders" / str(short.id) / "v1" / "short.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"mp4")
    (video.parent.parent / "cuts").mkdir()
    (video.parent.parent / "cuts" / "preview.mp4").write_bytes(b"mp4")
    strip = data / "previews" / f"{short.id}_10.00_40.00.jpg"
    strip.parent.mkdir(parents=True, exist_ok=True)
    strip.write_bytes(b"jpg")
    rel = video.relative_to(data).as_posix()
    db.add(
        MediaAsset(
            owner_type=AssetOwner.short_version, owner_id=v.id, kind=AssetKind.video, path=rel
        )
    )
    render = queue.enqueue(
        db, "short.render", {"short_id": str(short.id)}, subject=("short", short.id)
    )
    db.commit()
    STATE["render_job"] = render.id
    return short.id, video.parent.parent, strip


def test_permanent_delete_removes_files_and_records(client: TestClient, db: Session) -> None:
    sid, folder, strip = _seed_short(db)
    keep, _, _ = _seed_short(db)
    r = client.post("/api/v1/shorts/delete", json={"short_ids": [str(sid), str(uuid.uuid4())]})
    assert r.status_code == 200 and r.json() == {"deleted": [str(sid)]}
    assert not folder.exists() and not strip.exists()
    db.expire_all()
    assert db.get(Short, sid) is None
    for model, col in (
        (ShortPart, ShortPart.short_id),
        (ShortVersion, ShortVersion.short_id),
    ):
        assert db.scalar(select(func.count()).select_from(model).where(col == sid)) == 0
    assert db.scalar(select(func.count()).select_from(QcReport)) == 1  # the other Short's
    assert db.scalar(select(func.count()).select_from(MediaAsset)) == 1
    assert db.get(Short, keep) is not None
    assert client.get(f"/api/v1/shorts/{sid}").status_code == 404
    # its queued render was stopped
    j = db.scalar(select(Job).where(Job.subject_id == sid))
    assert j is not None and j.status == JobStatus.cancelled


def test_permanent_delete_validates_input(client: TestClient) -> None:
    assert client.post("/api/v1/shorts/delete", json={"short_ids": []}).status_code == 422


# ------------------------------------------------------------------ nothing stays stuck
def test_stopping_a_queued_render_puts_the_short_back(client: TestClient, db: Session) -> None:
    sid, _, _ = _seed_short(db)  # has a video and a queued render
    short = db.get(Short, sid)
    assert short is not None
    short.status = ShortStatus.rendering
    db.commit()
    client.post(f"/api/v1/jobs/{STATE['render_job']}/cancel")
    db.expire_all()
    assert db.get(Short, sid).status == ShortStatus.review  # type: ignore[union-attr]


def test_repair_frees_items_no_job_is_working_on(db: Session) -> None:
    from clipforge.db.enums import RunStatus
    from clipforge.db.models import Run
    from clipforge.services.repair import repair_orphans

    stuck, _, _ = _seed_short(db)  # its render job gets cancelled below
    busy, _, _ = _seed_short(db)  # its render job stays queued
    db.get(Short, stuck).status = ShortStatus.rendering  # type: ignore[union-attr]
    db.get(Short, busy).status = ShortStatus.rendering  # type: ignore[union-attr]
    job = db.scalar(select(Job).where(Job.subject_id == stuck))
    assert job is not None
    job.status = JobStatus.cancelled
    src = db.get(Short, stuck).source_id  # type: ignore[union-attr]
    db.get(Source, src).status = SourceStatus.analyzing  # type: ignore[union-attr]
    run = Run(status=RunStatus.running)
    db.add(run)
    db.commit()

    assert repair_orphans(db) == 3
    db.expire_all()
    assert db.get(Short, stuck).status == ShortStatus.review  # type: ignore[union-attr]
    assert db.get(Short, busy).status == ShortStatus.rendering  # type: ignore[union-attr]
    assert db.get(Source, src).status == SourceStatus.failed  # type: ignore[union-attr]
    assert db.get(Run, run.id).status == RunStatus.failed  # type: ignore[union-attr]
    assert repair_orphans(db) == 0


def test_api_requeues_jobs_of_a_dead_worker(db: Session) -> None:
    """Real bug: after a restart, jobs of the old workers showed "running" for many
    minutes because only an idle worker looked for expired leases."""
    import asyncio
    from datetime import timedelta

    from clipforge.db.base import utcnow

    job = queue.enqueue(db, "system.selftest")
    db.commit()
    queue.lease(db, "gone", ("cpu",), 60)
    j = queue.get(db, job.id)
    j.lease_until = utcnow() - timedelta(seconds=5)
    db.commit()
    app = create_app(Settings(job_lease_seconds=5))

    async def run() -> None:
        async with app.router.lifespan_context(app):
            await asyncio.sleep(5.5)

    asyncio.run(run())
    db.expire_all()
    assert queue.get(db, job.id).status == JobStatus.queued
