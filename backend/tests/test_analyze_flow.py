"""Analysis end to end: upload/link -> ingest -> analyze -> transcript, signals, timeline.

The speech model is the conftest FakeTranscriber (fixed words); media is real FFmpeg output.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from clipforge.api.app import create_app
from clipforge.core.config import get_settings
from clipforge.jobs.worker import Worker
from clipforge.pipeline.ingest.downloader import RemoteInfo, parse_info
from clipforge.pipeline.ingest.timewin import Window
from clipforge.pipeline.signals import vision as vision_sig
from clipforge.services import analyze as analyze_service
from clipforge.services import ingest as ingest_service

from .conftest import FakeTranscriber
from .media import make_audio, make_video, needs_ffmpeg
from .test_signals_units import yt_line

pytestmark = needs_ffmpeg


@pytest.fixture(scope="module")
def video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_video(tmp_path_factory.mktemp("m") / "talk.mp4", 12)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def run_all() -> None:
    w = Worker("t", caps=("cpu", "net", "ml"))
    for _ in range(10):
        if not w.run_once():
            return


def skip_backoff() -> None:
    from sqlalchemy import update

    from clipforge.db.models import Job
    from clipforge.db.session import get_sessionmaker

    with get_sessionmaker()() as s:
        s.execute(update(Job).values(available_at=None))
        s.commit()


def upload(client: TestClient, path: Path, **form: str) -> str:
    with path.open("rb") as f:
        r = client.post("/api/v1/sources/upload", files={"file": (path.name, f)}, data=form)
    assert r.status_code in (200, 201), r.text
    return str(r.json()["source"]["id"])


def test_upload_is_analysed_into_transcript_and_heat(client: TestClient, video: Path) -> None:
    sid = upload(client, video)
    run_all()
    src = client.get(f"/api/v1/sources/{sid}").json()
    assert src["status"] == "ready", src
    tr = client.get(f"/api/v1/sources/{sid}/transcript").json()
    assert [s["text"] for s in tr["segments"]] == ["The car crashed.", "Ha ha ha!", "No way."]
    assert tr["language"] == "en" and tr["word_count"] == 8
    laugh, reaction = tr["segments"][1], tr["segments"][2]
    assert laugh["heat"] > 0 and any(t["type"] == "LAUGH" for t in laugh["tags"])
    assert any(t["type"] == "MOMENT" for t in reaction["tags"])
    # words are kept on disk with full-video times
    words = json.loads(
        (get_settings().resolved_data_dir / "sources" / sid / "words.json").read_text()
    )
    assert words["words"][0][:3] == [0.5, 0.9, " The"]


def test_window_offset_applies_to_every_time(client: TestClient, video: Path) -> None:
    sid = upload(client, video, start="0:02", end="0:12")
    run_all()
    segs = client.get(f"/api/v1/sources/{sid}/transcript").json()["segments"]
    assert segs[0]["start_s"] == pytest.approx(2.5)  # 0.5 s into the audio + 2 s window start
    tl = client.get(f"/api/v1/sources/{sid}/timeline", params={"bins": 50}).json()
    assert (tl["start_s"], tl["end_s"]) == (2.0, 12.0)
    assert len(tl["heat"]) == len(tl["loud"]) == len(tl["chat"]) == 50
    assert {"loud", "moment", "laugh"} <= set(tl["available"])
    assert tl["steps"]["transcribe"].startswith("done")


def test_reanalysis_reuses_transcript_unless_forced(client: TestClient, video: Path) -> None:
    sid = upload(client, video)
    run_all()
    assert FakeTranscriber.calls == 1
    assert client.post(f"/api/v1/sources/{sid}/analyze", json={}).status_code == 200
    run_all()
    assert FakeTranscriber.calls == 1  # cached by audio hash
    client.post(f"/api/v1/sources/{sid}/analyze", json={"force_transcribe": True})
    run_all()
    assert FakeTranscriber.calls == 2
    assert (
        client.get(f"/api/v1/sources/{sid}/timeline")
        .json()["steps"]["transcribe"]
        .startswith("done")
    )


def test_analyze_conflicts(client: TestClient, video: Path) -> None:
    sid = upload(client, video)
    assert client.post(f"/api/v1/sources/{sid}/analyze", json={}).status_code == 409  # still new
    assert client.get(f"/api/v1/sources/{sid}/transcript").status_code == 404


def test_vision_motion_only_when_face_model_unavailable(
    client: TestClient, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_model(_d: Path) -> Path:
        raise OSError("offline")

    monkeypatch.setattr(vision_sig, "ensure_face_model", no_model)
    sid = upload(client, video)
    run_all()
    client.post(f"/api/v1/sources/{sid}/analyze", json={"vision": True})
    run_all()
    tl = client.get(f"/api/v1/sources/{sid}/timeline").json()
    assert tl["steps"]["vision"] == "done (motion only)"
    assert any("faces" in w for w in tl["warnings"])
    assert any(m > 0 for m in tl["motion"])  # testsrc2 moves
    detail = client.get(f"/api/v1/sources/{sid}").json()
    assert "proxy" in {a["kind"] for a in detail["assets"]}


def test_audio_only_source_skips_vision(client: TestClient, tmp_path: Path) -> None:
    sid = upload(client, make_audio(tmp_path / "pod.m4a", 10))
    run_all()
    client.post(f"/api/v1/sources/{sid}/analyze", json={"vision": True})
    run_all()
    assert (
        client.get(f"/api/v1/sources/{sid}/timeline").json()["steps"]["vision"]
        == "audio-only source"
    )


# ------------------------------------------------------------------ link source
class LinkDownloader:
    """Fake yt-dlp: real audio file, a chat replay with a spike, a heat map."""

    def __init__(self, audio: Path, chat: Path | None, fail_chat: bool = False) -> None:
        self.audio, self.chat, self.fail_chat = audio, chat, fail_chat

    def fetch_info(self, url: str, fallback: Any = None) -> RemoteInfo:
        return parse_info(
            {
                "id": "abcdefghijk",
                "extractor_key": "Youtube",
                "title": "Stream",
                "duration": 600,
                "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk",
                "heatmap": [
                    {
                        "start_time": i * 30,
                        "end_time": i * 30 + 30,
                        "value": 1.0 if i == 10 else 0.1,
                    }
                    for i in range(20)
                ],
            }
        )

    def download_audio(
        self, url: str, out_dir: Path, window: Window | None = None, **kw: Any
    ) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        return Path(shutil.copy(self.audio, out_dir / "audio.m4a"))

    def fetch_chat(self, url: str, out_dir: Path, **kw: Any) -> Path | None:
        if self.fail_chat:
            raise RuntimeError("chat endpoint changed")
        return self.chat


@pytest.fixture
def chat_file(tmp_path: Path) -> Path:
    lines = [yt_line(t * 1000, "hello") for t in range(0, 600, 4)]
    lines += [yt_line(int((300 + i * 0.15) * 1000), "LMAO", f"u{i}") for i in range(60)]
    p = tmp_path / "chat.live_chat.json"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def test_link_gets_chat_and_replay_signals(
    client: TestClient, tmp_path: Path, chat_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dl = LinkDownloader(make_audio(tmp_path / "a.m4a", 10), chat_file)
    monkeypatch.setattr(ingest_service, "make_downloader", lambda s: dl)
    sid = client.post("/api/v1/sources", json={"url": "https://youtu.be/abcdefghijk"}).json()[
        "source"
    ]["id"]
    run_all()
    tl = client.get(f"/api/v1/sources/{sid}/timeline", params={"bins": 60}).json()
    assert {"chat_spike", "replay"} <= set(tl["available"])
    types = {m["type"] for m in tl["markers"]}
    assert {"chat_spike", "replay"} <= types
    chat_m = next(m for m in tl["markers"] if m["type"] == "chat_spike")
    assert 290 <= chat_m["start_s"] <= 300 and "LMAO" in chat_m["label"]
    assert max(tl["chat"]) == 1.0 and max(tl["replay"]) == 1.0
    assert "messages" in tl["steps"]["chat"]


def test_whole_link_downloads_the_whole_video_copy_with_progress(
    client: TestClient, tmp_path: Path, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A link without "only part of the video" must not download a section (sections
    stream through ffmpeg: slow, no progress, no throttling recovery)."""
    windows: list[Window | None] = []
    steps: list[str] = []

    class WithVideo(LinkDownloader):
        def download_proxy(
            self, url: str, out_dir: Path, window: Window | None = None, **kw: Any
        ) -> Path:
            windows.append(window)
            kw["progress"](50.0, "downloading 1.0 of 2.0 MB")
            return Path(shutil.copy(video, out_dir / "proxy_src.mp4"))

    real_slice = analyze_service._Run.slice

    def spy(self: Any, lo: float, hi: float) -> Any:
        report = real_slice(self, lo, hi)

        def wrapped(pct: float, step: str | None = None) -> None:
            if step:
                steps.append(step)
            report(pct, step)

        return wrapped

    monkeypatch.setattr(analyze_service._Run, "slice", spy)
    monkeypatch.setenv("CF_VISION_ENABLED", "true")
    get_settings.cache_clear()

    def no_face_model(_d: Path) -> Path:
        raise RuntimeError("offline")  # motion only; no network in tests

    monkeypatch.setattr(vision_sig, "ensure_face_model", no_face_model)
    dl = WithVideo(make_audio(tmp_path / "a.m4a", 10), None)
    monkeypatch.setattr(ingest_service, "make_downloader", lambda s: dl)
    client.post("/api/v1/sources", json={"url": "https://youtu.be/abcdefghijk"})
    run_all()
    assert windows == [None]
    assert "video copy: downloading 1.0 of 2.0 MB" in steps


def test_failing_optional_step_is_a_warning_not_a_failure(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dl = LinkDownloader(make_audio(tmp_path / "a.m4a", 10), None, fail_chat=True)
    monkeypatch.setattr(ingest_service, "make_downloader", lambda s: dl)
    sid = client.post("/api/v1/sources", json={"url": "https://youtu.be/abcdefghijk"}).json()[
        "source"
    ]["id"]
    run_all()
    assert client.get(f"/api/v1/sources/{sid}").json()["status"] == "ready"
    tl = client.get(f"/api/v1/sources/{sid}/timeline").json()
    assert tl["steps"]["chat"] == "failed" and any(
        "chat endpoint changed" in w for w in tl["warnings"]
    )


def test_transcription_failure_fails_source_and_retry_only_reanalyses(
    client: TestClient, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken:
        def transcribe(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("model file corrupt")

    monkeypatch.setattr(analyze_service, "make_transcriber", lambda s: Broken())
    sid = upload(client, video)
    run_all()
    src = client.get(f"/api/v1/sources/{sid}").json()
    # first failure: a retry is queued and the reason is already visible
    assert src["status"] == "analyzing" and "model file corrupt" in src["error"]
    assert src["error_hint"].startswith("Retrying")
    skip_backoff()
    run_all()
    src = client.get(f"/api/v1/sources/{sid}").json()
    assert src["status"] == "failed" and "model file corrupt" in src["error"]
    monkeypatch.setattr(analyze_service, "make_transcriber", lambda s: FakeTranscriber())
    r = client.post(f"/api/v1/sources/{sid}/retry").json()
    job = client.get(f"/api/v1/jobs/{r['job_id']}").json()
    assert job["type"] == "source.analyze"  # audio exists: no re-download
    run_all()
    assert client.get(f"/api/v1/sources/{sid}").json()["status"] == "ready"
