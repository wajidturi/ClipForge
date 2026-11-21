"""Read models for rendered versions, and queuing renders."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from clipforge.db.enums import AssetKind, AssetOwner, JobStatus, ShortStatus
from clipforge.db.models import Job, MediaAsset, QcReport, Short, ShortVersion
from clipforge.jobs import queue

RENDER_JOB = "short.render"
EXTRA_KINDS = {AssetKind.aspect_4x5: "4:5", AssetKind.aspect_1x1: "1:1"}


class RenderStateError(ValueError):
    pass


def version_dicts(db: Session, version_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    if not version_ids:
        return {}
    vers = {
        v.id: v for v in db.scalars(select(ShortVersion).where(ShortVersion.id.in_(version_ids)))
    }
    qcs = {
        q.short_version_id: q
        for q in db.scalars(select(QcReport).where(QcReport.short_version_id.in_(version_ids)))
    }
    assets: dict[uuid.UUID, list[MediaAsset]] = {}
    for a in db.scalars(
        select(MediaAsset).where(
            MediaAsset.owner_type == AssetOwner.short_version, MediaAsset.owner_id.in_(version_ids)
        )
    ):
        assets.setdefault(a.owner_id, []).append(a)
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for vid, v in vers.items():
        by_kind = {a.kind: a for a in assets.get(vid, [])}
        q = qcs.get(vid)
        mp4 = by_kind.get(AssetKind.mp4)
        out[vid] = {
            "id": v.id,
            "version_no": v.version_no,
            "origin": v.origin.value,
            "layout": (v.settings or {}).get("layout_used"),
            "style": (v.settings or {}).get("style"),
            "mp4_asset_id": mp4.id if mp4 else None,
            "cover_asset_id": by_kind[AssetKind.cover].id if AssetKind.cover in by_kind else None,
            "extra_assets": {
                label: by_kind[k].id for k, label in EXTRA_KINDS.items() if k in by_kind
            },
            "qc_verdict": q.verdict.value if q else None,
            "qc_reasons": list(q.reasons) if q else [],
            "qc_checks": dict(q.checks) if q else {},
            "render_ms": v.render_ms,
            "duration_s": mp4.duration_s if mp4 else None,
            "created_at": v.created_at,
            "settings": dict(v.settings or {}),
        }
    return out


def latest_render_jobs(db: Session, short_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    if not short_ids:
        return {}
    rows = db.execute(
        select(Job.subject_id, Job.id)
        .where(Job.subject_type == "short", Job.subject_id.in_(short_ids), Job.type == RENDER_JOB)
        .order_by(Job.id)
    ).all()
    return {sid: jid for sid, jid in rows if sid is not None}  # later rows win: newest job


def enqueue_render(db: Session, short: Short, options: dict[str, Any]) -> Job:
    if short.status in (ShortStatus.rendering,):
        raise RenderStateError("this Short is already rendering")
    if short.status in (ShortStatus.dropped, ShortStatus.rejected):
        raise RenderStateError("dropped or rejected Shorts are not rendered")
    busy = db.scalar(
        select(Job.id).where(
            Job.subject_type == "short",
            Job.subject_id == short.id,
            Job.type == RENDER_JOB,
            Job.status.in_([JobStatus.queued, JobStatus.running]),
        )
    )
    if busy:
        raise RenderStateError("a render for this Short is already queued")
    job = queue.enqueue(
        db,
        RENDER_JOB,
        {"short_id": str(short.id), "options": options},
        label=f"Render: {(short.hook or 'Short')[:100]}",
        caps=("cpu", "net"),
        run_id=short.run_id,
        subject=("short", short.id),
        max_attempts=2,
    )
    short.status = ShortStatus.rendering
    return job
