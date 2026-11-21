"""System jobs. `system.selftest` exercises the whole job path end to end:
queue -> worker -> progress events -> WebSocket -> UI, including cancel and retry.
"""

from __future__ import annotations

from typing import Any

from clipforge.core.system import profile
from clipforge.jobs.registry import JobContext, PermanentJobError, job_handler


@job_handler("system.selftest", caps=("cpu",), public=True, description="Pipeline self-test")
def selftest(ctx: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
    steps = int(payload.get("steps", 10))
    delay = float(payload.get("delay", 0.4))
    fail_at = payload.get("fail_at")
    if not 1 <= steps <= 1000 or not 0 <= delay <= 10:
        raise PermanentJobError("steps must be 1..1000 and delay 0..10 s")
    for i in range(1, steps + 1):
        ctx.check_cancelled()
        if fail_at is not None and i == int(fail_at) and ctx.attempt == 1:
            raise RuntimeError(f"simulated failure at step {i} (succeeds on retry)")
        ctx.progress(100 * i / steps, f"step {i} of {steps}")
        ctx.sleep(delay)
    return {"steps": steps, "attempt": ctx.attempt}


@job_handler("system.profile", caps=("cpu",), public=True, description="Detect hardware")
def system_profile(ctx: JobContext, _payload: dict[str, Any]) -> dict[str, Any]:
    ctx.progress(10, "probing hardware")
    return profile(ctx.data_dir).to_dict()
