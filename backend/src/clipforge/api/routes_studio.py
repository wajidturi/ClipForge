"""Customization studio: scene + cut data for the live preview, template switching,
fonts for the browser, and the logo/image library."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from clipforge.api.deps import DB
from clipforge.api.routes_runs import get_short_or_404
from clipforge.api.schemas import CutOut, ImageOut, StudioData, TemplateSwitch
from clipforge.db.models import MediaAsset, ShortVersion, Source
from clipforge.pipeline.render import fonts
from clipforge.pipeline.render import scene as sc
from clipforge.services import brand_assets, cuts

router = APIRouter(tags=["studio"])


def _ctx(cut: cuts.Cut | None, duration: float) -> sc.Ctx:
    if cut is None:
        return sc.Ctx(duration, [], has_cam=True)
    d = cut.data
    return sc.Ctx(d["duration"], d["zoom_peaks"], has_cam=d["cam"] is not None)


@router.get("/shorts/{short_id}/studio", response_model=StudioData)
def studio(short_id: uuid.UUID, db: DB) -> StudioData:
    """The active version's scene and everything the live preview needs."""
    short = get_short_or_404(db, short_id)
    ver = db.get(ShortVersion, short.active_version_id) if short.active_version_id else None
    st = (ver.settings or {}) if ver else {}
    cut = cuts.load_cut(short.id, st["cut_key"]) if st.get("cut_key") else None
    rng = st.get("range") or [0, 30]
    ctx = _ctx(cut, float(rng[1]) - float(rng[0]))
    if st.get("scene"):
        scene = sc.Scene.model_validate(st["scene"])
    else:  # never rendered, or rendered before templates existed
        t, _ = sc.resolve_template(st.get("layout_used") or "auto", ctx.has_cam)
        scene = sc.default_scene(t, ctx)
    src = db.get(Source, short.source_id)
    values = {
        "hook": short.hook,
        "title": short.title,
        "channel": short.credit or (src.channel_name if src else "") or "",
        "reaction": (cut.data.get("reaction") if cut else None) or "NO WAY!",
    }
    cut_out = None
    if cut is not None and cut.data.get("preview_asset_id"):
        d = cut.data
        cut_out = CutOut(
            key=cut.key,
            preview_asset_id=uuid.UUID(d["preview_asset_id"]),
            src_w=d["src_w"],
            src_h=d["src_h"],
            duration=d["duration"],
            cam=d["cam"],
            targets=[(t, x) for t, x in d["targets"]],
            cuts=d["cuts"],
            zoom_peaks=d["zoom_peaks"],
            words=[(a, b, t, k) for a, b, t, k in d["words"]],
            reaction=d.get("reaction"),
        )
    return StudioData(
        version_id=ver.id if ver else None,
        scene=scene,
        note=st.get("note"),
        values=values,
        caption_overrides=dict(ver.caption_overrides or {}) if ver else {},
        cut=cut_out,
    )


@router.post("/shorts/{short_id}/scene/template", response_model=sc.Scene)
def switch_template(short_id: uuid.UUID, body: TemplateSwitch, db: DB) -> sc.Scene:
    """Defaults of another template for this Short, keeping the user's own layers
    (logo, text, emojis) and caption choices. Nothing is saved until a render."""
    short = get_short_or_404(db, short_id)
    ver = db.get(ShortVersion, short.active_version_id) if short.active_version_id else None
    st = (ver.settings or {}) if ver else {}
    cut = cuts.load_cut(short.id, st["cut_key"]) if st.get("cut_key") else None
    rng = st.get("range") or [0, 30]
    ctx = _ctx(cut, float(rng[1]) - float(rng[0]))
    t, _ = sc.resolve_template(body.template, ctx.has_cam if cut else True)
    if body.scene is None:
        return sc.default_scene(t, ctx)
    return sc.switch_template(body.scene, t, ctx)


# ------------------------------------------------------------------ fonts
@router.get("/fonts/{font_id}", response_class=FileResponse)
def font_file(font_id: str) -> FileResponse:
    """The exact font files the renderer uses, so the preview matches the export."""
    if font_id not in fonts.FONTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown font")
    path = fonts.font_path(font_id)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "font not installed")
    return FileResponse(
        path, media_type="font/ttf", headers={"Cache-Control": "public, max-age=604800"}
    )


# ------------------------------------------------------------------ images
def _image_out(a: MediaAsset) -> ImageOut:
    return ImageOut(
        id=a.id,
        name=a.codec,
        width=a.width,
        height=a.height,
    )


@router.get("/images", response_model=list[ImageOut])
def list_images(db: DB) -> list[ImageOut]:
    """Uploaded logos and images (shown at /media/{id})."""
    return [_image_out(a) for a in brand_assets.list_images(db)]


@router.post("/images", response_model=ImageOut, status_code=status.HTTP_201_CREATED)
async def upload_image(db: DB, file: Annotated[UploadFile, File()]) -> ImageOut:
    data = await file.read(brand_assets.MAX_BYTES + 1)
    try:
        a = await run_in_threadpool(brand_assets.save_image, db, data, file.filename)
    except brand_assets.ImageError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    return _image_out(a)


@router.delete("/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(image_id: uuid.UUID, db: DB) -> Response:
    if not brand_assets.delete_image(db, image_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "image not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
