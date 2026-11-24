"""Put things back in order when no job is working on them any more.

A Short shows "rendering", a source "downloading"/"analyzing" and a run "running"
only while a job for it is queued or running. If that job is gone (stopped while
queued by an older version, a crash, the app closed mid-way), the item would stay
stuck forever. This sweep runs at start-up and every few seconds in the workers.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from clipforge.core.logging import get_logger
from clipforge.db.base import utcnow
from clipforge.db.enums import JobStatus, RunStatus, ShortStatus, SourceStatus
from clipforge.db.models import Job, Run, Short, Source

log = get_logger(__name__)


def _busy(kind: str) -> Select[Any]:
    return select(Job.subject_id).where(
        Job.subject_type == kind,
        Job.subject_id.is_not(None),
        Job.status.in_([JobStatus.queued, JobStatus.running]),
    )


def repair_orphans(s: Session) -> int:
    """Returns how many items were fixed."""
    n = 0
    for short in s.scalars(
        select(Short).where(Short.status == ShortStatus.rendering, Short.id.not_in(_busy("short")))
    ):
        short.status = ShortStatus.review if short.active_version_id else ShortStatus.picked
        n += 1
    for src in s.scalars(
        select(Source).where(
            Source.status.in_([SourceStatus.downloading, SourceStatus.analyzing]),
            Source.id.not_in(_busy("source")),
        )
    ):
        src.status = SourceStatus.failed
        src.error = "Stopped before it finished"
        src.error_hint = "Use Retry to continue."
        n += 1
    for run in s.scalars(
        select(Run).where(
            Run.status.in_([RunStatus.queued, RunStatus.running]), Run.id.not_in(_busy("run"))
        )
    ):
        run.status = RunStatus.failed
        run.finished_at = utcnow()
        run.error = "Stopped before it finished"
        n += 1
    if n:
        s.commit()
        log.info("repair.orphans", fixed=n)
    return n
