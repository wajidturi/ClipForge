from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from clipforge.api.deps import DB
from clipforge.api.schemas import SettingField, SettingsOut, SettingsPatch
from clipforge.services import settings_store

router = APIRouter(tags=["settings"])


def _out(db: Any) -> SettingsOut:
    return SettingsOut(fields=[SettingField(**f) for f in settings_store.fields(db)])


@router.get("/settings", response_model=SettingsOut)
def get_settings_view(db: DB) -> SettingsOut:
    """Settings that can be changed in the app, with their current and default values."""
    return _out(db)


@router.patch("/settings", response_model=SettingsOut)
def update_settings(body: SettingsPatch, db: DB) -> SettingsOut:
    """Save values (validated all-or-nothing) and/or reset keys to their defaults."""
    try:
        settings_store.save(db, body.values, body.reset)
    except settings_store.SettingsError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"key": e.key, "message": e.message}
        ) from None
    return _out(db)
