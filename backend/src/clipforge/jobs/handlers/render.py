from __future__ import annotations

import uuid
from typing import Any

from clipforge.jobs.registry import JobContext, PermanentJobError, job_handler
from clipforge.services import render as render_service


@job_handler("short.render", caps=("cpu", "net"), description="Render a Short")
def render(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        short_id = uuid.UUID(str(payload["short_id"]))
    except (KeyError, ValueError):
        raise PermanentJobError("payload needs a valid 'short_id'") from None
    return render_service.render(ctx, short_id, payload.get("options") or {})
