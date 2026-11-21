"""End-to-end ingestion through the API and a real worker, with real FFmpeg media.

Links use a fake downloader (no network); files are real generated videos.
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from clipforge.api.app import create_app
from clipforge.core.config import get_settings
from clipforge.db.enums import JobStatus
from clipforge.db.models import Job
from clipforge.db.session import get_sessionmaker
from clipforge.jobs.worker import Worker
from clipforge.pipeline.ingest.downloader import DownloadError, RemoteInfo, parse_info
from clipforge.pipeline.ingest.timewin import Window
from clipforge.services import ingest as ingest_service
from clipforge.services.segments import ensure_segment

from .media import make_audio, make_video, needs_ffmpeg

pytestmark = needs_ffmpeg


@pytest.fixture(scope="session")
def video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_video(tmp_path_factory.mktemp("media") / "clip.mp4", 20)


@pytest.fixture(scope="session")
def audio(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_audio(tmp_path_factory.mktemp("media") / "audio.m4a", 15)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def run_jobs(n: int = 5) -> None:
    w = Worker("test", caps=("cpu", "net", "ml"))
    for _ in range(n):
        if not w.run_once():
            return


def last_job() -> Job:
    with get_sessionmaker()() as s:
        job = s.scalars(select(Job).order_by(Job.id.desc())).first()
        assert job is not None
        s.expunge(job)
        return job


# ------------------------------------------------------------------ uploads
def upload(client: TestClient, path: Path, name: str | None = None, **form: str) -> Any:
    with path.open("rb") as f:
        return client.post(
            "/api/v1/sources/upload", files={"file": (name or path.name, f)}, data=form
        )


def test_upload_video_becomes_ready_with_audio_and_video(client: TestClient, video: Path) -> None:
    r = upload(client, video)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] and body["source"]["platform"] == "file"
    assert body["source"]["status"] == "new" and body["job_id"]
    run_jobs()
    src = client.get(f"/api/v1/sources/{body['source']['id']}").json()
    assert src["status"] == "ready", src
    kinds = {a["kind"]: a for a in src["assets"]}
    assert set(kinds) == {"audio", "video"}
    assert kinds["audio"]["duration_s"] == pytest.approx(20, abs=0.5)
    assert kinds["video"]["width"] == 640 and src["duration_s"] == pytest.approx(20, abs=0.5)
    assert src["title"] == "clip"

    # media streaming supports ranges (players need this to seek)
    m = client.get(f"/api/v1/media/{kinds['audio']['id']}", headers={"Range": "bytes=0-99"})
    assert m.status_code == 206 and len(m.content) == 100
    assert m.headers["content-type"].startswith("audio/")


def test_upload_same_file_twice_is_deduplicated(client: TestClient, video: Path) -> None:
    first = upload(client, video).json()
    again = upload(client, video, name="renamed.mp4")
    assert again.status_code == 200
    assert again.json()["created"] is False
    assert again.json()["source"]["id"] == first["source"]["id"]


def test_upload_with_window_cuts_audio(client: TestClient, video: Path) -> None:
    r = upload(client, video, start="0:05", end="0:15").json()
    run_jobs()
    src = client.get(f"/api/v1/sources/{r['source']['id']}").json()
    audio_asset = next(a for a in src["assets"] if a["kind"] == "audio")
    assert audio_asset["duration_s"] == pytest.approx(10, abs=0.5)
    assert (src["window_start_s"], src["window_end_s"]) == (5, 15)


def test_upload_audio_only_file(client: TestClient, audio: Path) -> None:
    r = upload(client, audio).json()
    run_jobs()
    src = client.get(f"/api/v1/sources/{r['source']['id']}").json()
    assert src["status"] == "ready" and [a["kind"] for a in src["assets"]] == ["audio"]


def test_upload_fake_media_fails_with_message(client: TestClient, tmp_path: Path) -> None:
    junk = tmp_path / "notes.mp4"
    junk.write_text("this is not a video")
    r = upload(client, junk).json()
    run_jobs()
    src = client.get(f"/api/v1/sources/{r['source']['id']}").json()
    assert src["status"] == "failed" and "could not be read" in src["error"]
    assert (
        last_job().status == JobStatus.failed and last_job().attempts == 1
    )  # no pointless retries


def test_upload_silent_video_rejected(client: TestClient, tmp_path: Path) -> None:
    r = upload(client, make_video(tmp_path / "silent.mp4", 3, audio=False)).json()
    run_jobs()
    src = client.get(f"/api/v1/sources/{r['source']['id']}").json()
    assert src["status"] == "failed" and "no audio" in src["error"]


def test_upload_rejects_bad_extension_and_window(
    client: TestClient, tmp_path: Path, video: Path
) -> None:
    bad = tmp_path / "virus.exe"
    bad.write_bytes(b"MZ")
    assert upload(client, bad).status_code == 422
    assert upload(client, video, start="2:00", end="1:00").status_code == 422


# ------------------------------------------------------------------ links (fake downloader)
class FakeDownloader:
    def __init__(self, audio: Path, video: Path, info: dict[str, Any], error: str | None = None):
        self.audio, self.video, self.info, self.error = audio, video, info, error
        self.windows: list[Window | None] = []

    def fetch_info(self, url: str, fallback: Any = None) -> RemoteInfo:
        if self.error:
            raise DownloadError(self.error)
        return parse_info(self.info)

    def download_audio(
        self, url: str, out_dir: Path, window: Window | None = None, **kw: Any
    ) -> Path:
        self.windows.append(window)
        if kw.get("progress"):
            kw["progress"](50.0, "downloading 1 of 2 MB")
        out_dir.mkdir(parents=True, exist_ok=True)
        return Path(shutil.copy(self.audio, out_dir / "audio.m4a"))

    def download_section(
        self, url: str, out_dir: Path, start_s: float, end_s: float, **kw: Any
    ) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        return Path(shutil.copy(self.video, out_dir / f"{kw.get('stem', 'segment')}.mp4"))


INFO = {
    "id": "dQw4w9WgXcQ",
    "extractor_key": "Youtube",
    "title": "Huge reaction",
    "channel": "Creator",
    "duration": 15,
    "upload_date": "20261119",
    "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hq.jpg",
    "heatmap": [{"start_time": 0, "end_time": 1, "value": 1}],
}


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, audio: Path, video: Path) -> FakeDownloader:
    f = FakeDownloader(audio, video, dict(INFO))
    monkeypatch.setattr(ingest_service, "make_downloader", lambda settings: f)
    return f


def add(client: TestClient, url: str, **kw: str) -> Any:
    return client.post("/api/v1/sources", json={"url": url, **kw})


def test_link_ingest_fills_metadata(client: TestClient, fake: FakeDownloader) -> None:
    r = add(client, "https://youtu.be/dQw4w9WgXcQ")
    assert r.status_code == 201
    run_jobs()
    src = client.get(f"/api/v1/sources/{r.json()['source']['id']}").json()
    assert src["status"] == "ready", src
    assert src["title"] == "Huge reaction" and src["channel_name"] == "Creator"
    assert src["thumbnail"].endswith("hq.jpg") and src["has_heatmap"]
    assert src["published_at"].startswith("2026-11-19")
    assert [a["kind"] for a in src["assets"]] == ["audio"]
    assert fake.windows == [None]


def test_same_video_different_link_is_deduplicated(
    client: TestClient, fake: FakeDownloader
) -> None:
    a = add(client, "https://youtu.be/dQw4w9WgXcQ").json()
    b = add(client, "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10")
    assert b.status_code == 200 and b.json()["source"]["id"] == a["source"]["id"]


def test_long_video_gets_default_window(client: TestClient, fake: FakeDownloader) -> None:
    fake.info["duration"] = 8 * 3600
    r = add(client, "https://youtu.be/dQw4w9WgXcQ").json()
    run_jobs()
    src = client.get(f"/api/v1/sources/{r['source']['id']}").json()
    assert (src["window_start_s"], src["window_end_s"]) == (6 * 3600, 8 * 3600)
    assert "last 2 h" in src["window_note"]
    assert fake.windows == [Window(6 * 3600, 8 * 3600)]


def test_explicit_window_is_used(client: TestClient, fake: FakeDownloader) -> None:
    fake.info["duration"] = 3600
    r = add(client, "https://youtu.be/dQw4w9WgXcQ", start="10:00", end="20:00").json()
    run_jobs()
    assert fake.windows == [Window(600, 1200)]
    assert client.get(f"/api/v1/sources/{r['source']['id']}").json()["window_note"] is None


def test_live_stream_is_refused(client: TestClient, fake: FakeDownloader) -> None:
    fake.info["live_status"] = "is_live"
    r = add(client, "https://youtu.be/dQw4w9WgXcQ").json()
    run_jobs()
    src = client.get(f"/api/v1/sources/{r['source']['id']}").json()
    assert src["status"] == "failed" and "live stream" in src["error"]


def test_private_video_fails_with_hint_no_retry(client: TestClient, fake: FakeDownloader) -> None:
    fake.error = (
        "ERROR: [youtube] dQw4w9WgXcQ: Private video. Sign in if you've been granted access"
    )
    r = add(client, "https://youtu.be/dQw4w9WgXcQ").json()
    run_jobs()
    src = client.get(f"/api/v1/sources/{r['source']['id']}").json()
    assert src["status"] == "failed" and src["error_hint"]
    assert last_job().attempts == 1


def test_rate_limit_retries_then_recovers(client: TestClient, fake: FakeDownloader) -> None:
    fake.error = "ERROR: HTTP Error 429: Too Many Requests"
    r = add(client, "https://youtu.be/dQw4w9WgXcQ").json()
    run_jobs(1)
    src = client.get(f"/api/v1/sources/{r['source']['id']}").json()
    assert src["status"] == "downloading" and "rate-limiting" in src["error"]  # retry pending
    job = last_job()
    assert job.status == JobStatus.queued
    fake.error = None
    with get_sessionmaker()() as s:
        s.get(Job, job.id).available_at = None  # type: ignore[union-attr]  # skip backoff
        s.commit()
    run_jobs()
    assert client.get(f"/api/v1/sources/{r['source']['id']}").json()["status"] == "ready"


def test_invalid_links_rejected(client: TestClient) -> None:
    for bad in ["http://localhost/x", "https://www.youtube.com/playlist?list=PL1", "nope"]:
        assert add(client, bad).status_code == 422, bad


def test_retry_and_delete(client: TestClient, fake: FakeDownloader) -> None:
    fake.error = "ERROR: Video unavailable"
    r = add(client, "https://youtu.be/dQw4w9WgXcQ").json()
    sid = r["source"]["id"]
    run_jobs()
    assert client.get(f"/api/v1/sources/{sid}").json()["status"] == "failed"
    fake.error = None
    assert client.post(f"/api/v1/sources/{sid}/retry").status_code == 200
    run_jobs()
    assert client.get(f"/api/v1/sources/{sid}").json()["status"] == "ready"
    folder = get_settings().resolved_data_dir / "sources" / sid
    assert folder.exists()
    assert client.delete(f"/api/v1/sources/{sid}").status_code == 204
    assert client.get(f"/api/v1/sources/{sid}").status_code == 404
    assert not folder.exists()


def test_list_search_and_filter(client: TestClient, fake: FakeDownloader, video: Path) -> None:
    add(client, "https://youtu.be/dQw4w9WgXcQ")
    upload(client, video)
    run_jobs()
    assert len(client.get("/api/v1/sources").json()["items"]) == 2
    assert [
        s["platform"]
        for s in client.get("/api/v1/sources", params={"platform": "file"}).json()["items"]
    ] == ["file"]
    hits = client.get("/api/v1/sources", params={"q": "huge"}).json()["items"]
    assert [s["title"] for s in hits] == ["Huge reaction"]
    assert len(client.get("/api/v1/sources/platforms").json()) == 11


def test_websocket_reports_source_updates(client: TestClient, video: Path) -> None:
    with client.websocket_connect("/api/v1/ws") as ws:
        sid = upload(client, video).json()["source"]["id"]
        run_jobs()
        statuses = []
        while "ready" not in statuses:
            msg = json.loads(ws.receive_text())
            if msg["type"] == "source.updated" and msg["source"]["id"] == sid:
                statuses.append(msg["source"]["status"])
        assert statuses[-1] == "ready"


def test_misaligned_window_download_is_caught(audio: Path) -> None:
    """A 15 s file for a 5 s window means the cut started early: must not pass silently."""
    with pytest.raises(DownloadError, match="misaligned"):
        ingest_service.check_window_alignment(audio, Window(100, 105))
    ingest_service.check_window_alignment(audio, Window(100, 115))  # matches: fine
    ingest_service.check_window_alignment(audio, None)


# ------------------------------------------------------------------ segments
def test_segment_from_uploaded_file_is_cut_and_cached(client: TestClient, video: Path) -> None:
    sid = uuid.UUID(upload(client, video).json()["source"]["id"])
    run_jobs()
    a = ensure_segment(sid, 4.0, 9.0)
    assert a.duration_s == pytest.approx(5, abs=0.2) and a.width == 640
    assert (get_settings().resolved_data_dir / a.path).exists()
    assert ensure_segment(sid, 4.0, 9.0).id == a.id  # cached, not re-cut


def test_segment_from_link_uses_range_download(client: TestClient, fake: FakeDownloader) -> None:
    sid = uuid.UUID(add(client, "https://youtu.be/dQw4w9WgXcQ").json()["source"]["id"])
    run_jobs()
    a = ensure_segment(sid, 1.0, 6.0)
    assert a.path.endswith(".mp4") and a.kind == "segment"
