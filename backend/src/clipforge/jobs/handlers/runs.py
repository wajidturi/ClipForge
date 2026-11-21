from __future__ import annotations

import uuid
from typing import Any

from clipforge.jobs.registry import JobCancelledError, JobContext, PermanentJobError, job_handler
from clipforge.services import runs


@job_handler("run.select", caps=("cpu",), description="Pick the best moments for a run")
def select(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        run_id = uuid.UUID(str(payload["run_id"]))
    except (KeyError, ValueError):
        raise PermanentJobError("payload needs a valid 'run_id'") from None
    try:
        return runs.select_moments(ctx, run_id)
    except JobCancelledError:
        runs.fail_run(run_id, "Cancelled")
        raise
    except PermanentJobError as e:
        runs.fail_run(run_id, str(e))
        raise
    except Exception as e:
        if ctx.is_last_attempt:
            runs.fail_run(run_id, f"Picking failed: {e}")
        raise
