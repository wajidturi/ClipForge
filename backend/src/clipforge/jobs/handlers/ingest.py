from __future__ import annotations

import uuid
from typing import Any

from clipforge.jobs.registry import JobContext, PermanentJobError, job_handler
from clipforge.services import analyze as analyze_service
from clipforge.services import ingest as ingest_service
from clipforge.services import segments


def _uuid(payload: dict[str, Any], key: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(payload[key]))
    except (KeyError, ValueError):
        raise PermanentJobError(f"payload needs a valid '{key}'") from None


@job_handler("source.ingest", caps=("cpu", "net"), description="Download / read a source")
def ingest(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    return ingest_service.ingest(ctx, _uuid(payload, "source_id"))


@job_handler(
    "source.analyze", caps=("cpu", "net", "ml"), description="Transcript, signals and HEAT"
)
def analyze(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    return analyze_service.analyze(ctx, _uuid(payload, "source_id"), payload.get("options") or {})


@job_handler("source.segment", caps=("cpu", "net"), description="Fetch a video segment")
def segment(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    asset = segments.ensure_segment(
        _uuid(payload, "source_id"),
        float(payload["start"]),
        float(payload["end"]),
        is_cancelled=lambda: ctx.cancelled,
        progress=lambda pct, step: ctx.progress(None if pct < 0 else pct, step),
    )
    return {"asset_id": str(asset.id), "path": asset.path}
