"""Serve stored media (audio/video) with HTTP range support so players can seek."""

from __future__ import annotations

import mimetypes
import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from clipforge.api.deps import DB, Config
from clipforge.db.models import MediaAsset

router = APIRouter(prefix="/media", tags=["media"])

MIME = {".m4a": "audio/mp4", ".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska"}


@router.get("/{asset_id}", response_class=FileResponse)
def get_media(asset_id: uuid.UUID, db: DB, settings: Config) -> FileResponse:
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "media not found")
    root = settings.resolved_data_dir.resolve()
    path = (root / asset.path).resolve()
    # Paths come from our own DB, but never serve anything outside the data dir.
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "media file is missing")
    media_type = MIME.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
    return FileResponse(path, media_type=media_type or "application/octet-stream")
