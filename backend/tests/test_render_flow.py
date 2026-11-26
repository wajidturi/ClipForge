"""Golden render tests: real FFmpeg output from a generated video, through API + worker."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from clipforge.api.app import create_app
from clipforge.core import ffmpeg
from clipforge.core.config import get_settings
from clipforge.db.enums import Platform, ShortStatus, SourceStatus
from clipforge.db.models import Run, Segment, Short, ShortPart, Source, Transcript
from clipforge.db.session import get_sessionmaker
from clipforge.jobs.worker import Worker
from clipforge.pipeline.render import reframe
from clipforge.pipeline.render.reframe import Box
from clipforge.pipeline.signals import vision as vision_sig
from clipforge.pipeline.signals.audio import decode_pcm
from clipforge.services import render as render_svc

from .media import make_video, needs_ffmpeg

pytestmark = needs_ffmpeg


@pytest.fixture(autouse=True)
def offline_faces(monkeypatch: pytest.MonkeyPatch) -> None:
    def none(_d: Path) -> Path:
        raise OSError("offline in tests")

    monkeypatch.setattr(vision_sig, "ensure_face_model", none)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def seed_short(
    video_s: float = 40, start: float = 10, end: float = 30, hook: str = "BIG MOMENT"
) -> str:
    """A file source with a real video, word timings every 0.5 s, and one picked Short."""
    data = get_settings().resolved_data_dir
    sid = uuid.uuid4()
    folder = data / "sources" / str(sid)
    folder.mkdir(parents=True)
    make_video(folder / "original.mp4", video_s)
    words = []
    t = 1.0
    i = 0
    while t < video_s - 1:
        if not (18 <= t < 21):  # a 3 s silence to cut
            words.append([t, t + 0.4, f" word{i}" + ("." if i % 6 == 5 else ""), 0.9])
            i += 1
        t += 0.5
    (folder / "words.json").write_text(json.dumps({"words": words}))
    with get_sessionmaker()() as s:
        s.add(
            Source(
                id=sid,
                platform=Platform.file,
                external_id=sid.hex,
                url="file:x.mp4",
                title="clip",
                status=SourceStatus.ready,
                duration_s=video_s,
            )
        )
        tr = Transcript(
            source_id=sid,
            model="m",
            device="cpu",
            language="en",
            words_path=f"sources/{sid}/words.json",
            word_count=len(words),
        )
        s.add(tr)
        s.flush()
        for n, k in enumerate(range(0, len(words), 6)):
            chunk = words[k : k + 6]
            s.add(
                Segment(
                    transcript_id=tr.id,
                    idx=n,
                    start_s=chunk[0][0],
                    end_s=chunk[-1][1],
                    text=" ".join(w[2] for w in chunk),
                    heat=60 if 20 <= chunk[0][0] <= 24 else 5,
                    tags=[],
                )
            )
        run = Run(params={"n": 1, "pick_mode": "free"})
        s.add(run)
        s.flush()
        short = Short(
            run_id=run.id,
            source_id=sid,
            hook=hook,
            title="t",
            hashtags=["#shorts"],
            keywords=["WORD3"],
            status=ShortStatus.picked,
        )
        s.add(short)
        s.flush()
        s.add(ShortPart(short_id=short.id, idx=0, start_s=start, end_s=end))
        s.commit()
        return str(short.id)


def run_jobs() -> None:
    w = Worker("t", caps=("cpu", "net"))
    for _ in range(4):
        if not w.run_once():
            return


def media_path(asset_id: str) -> Path:
    from clipforge.db.models import MediaAsset

    with get_sessionmaker()() as s:
        a = s.get(MediaAsset, uuid.UUID(asset_id))
        assert a is not None
        return get_settings().resolved_data_dir / a.path


def render(client: TestClient, short_id: str, **body: Any) -> dict[str, Any]:
    r = client.post(f"/api/v1/shorts/{short_id}/render", json=body)
    assert r.status_code == 202, r.text
    run_jobs()
    return client.get(f"/api/v1/shorts/{short_id}").json()


def test_render_produces_a_vertical_short_that_passes_qc(client: TestClient) -> None:
    sid = seed_short()
    short = render(client, sid)
    assert short["status"] == "review", short
    v = short["active"]
    assert v["version_no"] == 1 and v["layout"] == "cinematic"
    assert v["qc_verdict"] in ("pass", "warn")
    mp4 = media_path(v["mp4_asset_id"])
    info = ffmpeg.probe(mp4)
    assert (info.video.width, info.video.height) == (1080, 1920) and info.has_audio
    # 20 s range minus the 3 s silence (cut to 0.2 s) ~= 17.5 s
    assert 16.5 <= (info.duration_s or 0) <= 18.5
    checks = short["versions"][0]["qc_checks"]
    assert abs(checks["lufs"] + 14) <= 1.5 and checks["caption_coverage"] >= 0.9
    assert checks["black"] == []
    cover = media_path(v["cover_asset_id"])
    assert cover.read_bytes()[:2] == b"\xff\xd8"
    assert len(decode_pcm(mp4)) > 16000 * 16


def test_rerender_creates_a_new_version_with_extra_aspect(client: TestClient) -> None:
    sid = seed_short()
    render(client, sid)
    with get_sessionmaker()() as s:  # a reviewed Short can be rendered again
        assert s.get(Short, uuid.UUID(sid)).status == ShortStatus.review  # type: ignore[union-attr]
    short = render(client, sid, style="word", layout="full", aspects=["4:5"])
    assert [v["version_no"] for v in short["versions"]] == [2, 1]
    v2 = short["active"]
    assert v2["origin"] == "rerender" and v2["layout"] == "cinematic" and v2["style"] == "word"
    extra = ffmpeg.probe(media_path(v2["extra_assets"]["4:5"]))
    assert (extra.video.width, extra.video.height) == (1080, 1350)
    # version 1 is still there, untouched
    assert media_path(short["versions"][1]["mp4_asset_id"]).exists()


@pytest.mark.parametrize("layout", ["streamer_first", "floating_facecam"])
def test_facecam_layouts_render(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, layout: str
) -> None:
    monkeypatch.setattr(
        reframe,
        "find_people",
        lambda samples: reframe.People("overlay", [Box(0.75, 0.05, 0.2, 0.3)]),
    )
    sid = seed_short(video_s=24, start=4, end=18)
    short = render(client, sid, template=layout, style="karaoke")
    assert short["status"] == "review", short["versions"][0]["qc_reasons"]
    assert short["active"]["layout"] == layout
    info = ffmpeg.probe(media_path(short["active"]["mp4_asset_id"]))
    assert (info.video.width, info.video.height) == (1080, 1920)


def test_render_run_queues_all_picks_and_rejects_double_render(client: TestClient) -> None:
    sid = seed_short()
    with get_sessionmaker()() as s:
        run_id = str(s.get(Short, uuid.UUID(sid)).run_id)  # type: ignore[union-attr]
    r = client.post(f"/api/v1/runs/{run_id}/render", json={"style": "box"})
    assert r.status_code == 202 and len(r.json()["job_ids"]) == 1
    assert client.post(f"/api/v1/shorts/{sid}/render", json={}).status_code == 409  # already queued
    assert client.post(f"/api/v1/runs/{run_id}/render", json={}).status_code == 409  # nothing left
    run_jobs()
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["shorts"][0]["active"]["style"] == "box"
    assert detail["shorts"][0]["render_job_id"] == r.json()["job_ids"][0]
    assert client.post(f"/api/v1/shorts/{sid}/render", json={"style": "nope"}).status_code == 422


def test_render_options(client: TestClient) -> None:
    o = client.get("/api/v1/render/options").json()
    assert {s["id"] for s in o["styles"]} == {
        "gaming",
        "classic",
        "word",
        "box",
        "karaoke",
        "minimal",
    }
    assert [x["id"] for x in o["templates"]] == [
        "streamer_first",
        "gameplay_first",
        "dual_vision",
        "floating_facecam",
        "cinematic",
    ]
    assert "impact" in {f["id"] for f in o["fonts"]}
    assert o["caption_presets"]["gaming"]["font"] == "impact"
    assert o["encoder"] in ("CPU (x264)", "GPU (NVENC)")


def test_recut_rules() -> None:
    info = {"sentences": [(10.0, 13.0), (13.5, 16.0), (16.5, 30.0), (30.5, 33.0)]}
    assert render_svc._recut(info, 10.0, 30.0, ["starts on a black frame"]) == (13.5, 30.0)
    assert render_svc._recut(info, 10.0, 30.0, ["too short (6.0s)"]) == (10.0, 33.0)
    assert render_svc._recut(info, 10.0, 30.0, ["loudness -30 LUFS"]) is None
