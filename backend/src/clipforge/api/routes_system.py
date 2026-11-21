from __future__ import annotations

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from clipforge import __version__
from clipforge.api.deps import Config
from clipforge.api.schemas import CheckOut, DoctorOut, HealthOut, SystemOut
from clipforge.core import system

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthOut)
def health(settings: Config) -> HealthOut:
    return HealthOut(version=__version__, mode=settings.mode)


@router.get("/system", response_model=SystemOut)
async def system_info(settings: Config) -> SystemOut:
    p = await run_in_threadpool(system.profile, settings.resolved_data_dir)
    return SystemOut(
        **p.to_dict(),
        data_dir=str(settings.resolved_data_dir),
        database="sqlite" if settings.is_sqlite else "postgresql",
    )


@router.get("/system/doctor", response_model=DoctorOut)
async def doctor(settings: Config) -> DoctorOut:
    p = await run_in_threadpool(system.profile, settings.resolved_data_dir)
    checks = [CheckOut(**c.__dict__) for c in system.doctor(p)]
    return DoctorOut(ok=all(c.ok for c in checks if c.required), checks=checks)
