"""Uploaded images: channel logos, watermarks, custom stickers.

Uploads are decoded with Pillow (so anything that is not really an image is
refused), converted to RGBA PNG (metadata stripped), shrunk to at most 1600 px and
stored under ``data/brand/``. They are reusable across Shorts; a scene layer
points at one by its asset id.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from clipforge.core.config import get_settings
from clipforge.core.hashing import sha256_file
from clipforge.db.enums import AssetKind, AssetOwner
from clipforge.db.models import MediaAsset
from clipforge.db.session import get_sessionmaker

MAX_BYTES = 10 * 1024 * 1024
MAX_SIDE = 1600
LIBRARY_ID = uuid.UUID(int=0)  # owner id for the shared image library


class ImageError(ValueError):
    pass


def save_image(db: Session, data: bytes, name: str | None = None) -> MediaAsset:
    if len(data) > MAX_BYTES:
        raise ImageError("images can be at most 10 MB")
    try:
        img: Image.Image = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise ImageError("this file is not a PNG, JPG, WebP or GIF image") from None
    if img.width < 8 or img.height < 8:
        raise ImageError("the image is too small")
    img = img.convert("RGBA")
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    root = get_settings().resolved_data_dir
    folder = root / "brand"
    folder.mkdir(parents=True, exist_ok=True)
    aid = uuid.uuid4()
    path = folder / f"{aid.hex}.png"
    img.save(path, "PNG", optimize=True)
    asset = MediaAsset(
        id=aid,
        owner_type=AssetOwner.brand,
        owner_id=LIBRARY_ID,
        kind=AssetKind.image,
        path=path.relative_to(root).as_posix(),
        bytes=path.stat().st_size,
        sha256=sha256_file(path),
        width=img.width,
        height=img.height,
        codec=(name or "image")[:40],
    )
    db.add(asset)
    db.commit()
    return asset


def list_images(db: Session) -> list[MediaAsset]:
    return list(
        db.scalars(
            select(MediaAsset)
            .where(MediaAsset.owner_type == AssetOwner.brand, MediaAsset.kind == AssetKind.image)
            .order_by(MediaAsset.id.desc())
        )
    )


def delete_image(db: Session, asset_id: uuid.UUID) -> bool:
    a = db.get(MediaAsset, asset_id)
    if a is None or a.owner_type != AssetOwner.brand:
        return False
    (get_settings().resolved_data_dir / a.path).unlink(missing_ok=True)
    db.delete(a)
    db.commit()
    return True


def image_path(asset_id: str) -> Path | None:
    """File of an uploaded image (used by the renderer); None if it is gone."""
    try:
        aid = uuid.UUID(asset_id)
    except ValueError:
        return None
    with get_sessionmaker()() as s:
        a = s.get(MediaAsset, aid)
        if a is None or a.owner_type != AssetOwner.brand:
            return None
        p = get_settings().resolved_data_dir / a.path
        return p if p.exists() else None
