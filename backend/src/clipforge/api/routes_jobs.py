from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from clipforge.api.deps import DB
from clipforge.api.schemas import JobCreate, JobOut, JobPage, JobTypeOut
from clipforge.db.enums import JobStatus
from clipforge.db.models import Job
from clipforge.jobs import queue
from clipforge.jobs.registry import all_specs, get_spec

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _get(db: DB, job_id: uuid.UUID) -> Job:
    try:
        return queue.get(db, job_id)
    except queue.JobNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found") from None


@router.get("/types", response_model=list[JobTypeOut])
def job_types() -> list[JobTypeOut]:
    return [
        JobTypeOut(type=s.type, caps=list(s.caps), description=s.description)
        for s in all_specs()
        if s.public
    ]


@router.get("", response_model=JobPage)
def list_jobs(
    db: DB,
    status_: Annotated[JobStatus | None, Query(alias="status")] = None,
    type_: Annotated[str | None, Query(alias="type")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[uuid.UUID | None, Query(description="id of the last item seen")] = None,
) -> JobPage:
    # UUIDv7 ids are unique and time-ordered, so they make a stable keyset cursor
    # (created_at alone can collide when jobs are created in the same instant).
    q = select(Job).order_by(Job.id.desc()).limit(limit + 1)
    if status_:
        q = q.where(Job.status == status_)
    if type_:
        q = q.where(Job.type == type_)
    if cursor:
        q = q.where(Job.id < cursor)
    rows = list(db.scalars(q).all())
    more = len(rows) > limit
    rows = rows[:limit]
    return JobPage(
        items=[JobOut.model_validate(r) for r in rows],
        next_cursor=str(rows[-1].id) if more and rows else None,
    )


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(body: JobCreate, db: DB) -> JobOut:
    spec = get_spec(body.type)
    if spec is None or not spec.public:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown job type '{body.type}'"
        )
    job = queue.enqueue(
        db, spec.type, body.payload, label=body.label, caps=spec.caps, priority=body.priority
    )
    db.commit()
    return JobOut.model_validate(job)


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, db: DB) -> JobOut:
    return JobOut.model_validate(_get(db, job_id))


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: uuid.UUID, db: DB) -> JobOut:
    _get(db, job_id)
    try:
        return JobOut.model_validate(queue.request_cancel(db, job_id))
    except queue.InvalidJobStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None


@router.post("/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: uuid.UUID, db: DB) -> JobOut:
    _get(db, job_id)
    try:
        return JobOut.model_validate(queue.retry(db, job_id))
    except queue.InvalidJobStateError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
