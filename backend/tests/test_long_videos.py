"""Long sources: many Shorts from one video, length presets, fast long-part downloads."""

from __future__ import annotations

import itertools
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from clipforge.ai.prompts import select_user_message
from clipforge.api.app import create_app
from clipforge.core import ffmpeg
from clipforge.core.config import Settings
from clipforge.db.enums import Platform, SourceStatus
from clipforge.db.models import Segment, Source, Transcript
from clipforge.db.session import get_sessionmaker
from clipforge.jobs.worker import Worker
from clipforge.pipeline.ingest import downloader
from clipforge.pipeline.ingest.downloader import Downloader, is_long_section
from clipforge.pipeline.ingest.timewin import Window, default_window
from clipforge.pipeline.selection import Sent
from clipforge.pipeline.selection.windows import LENGTHS, build_candidates

from .media import make_audio, needs_ffmpeg

HOT_EVERY = 60  # sentences (5 min): one hot moment each


def word(n: int) -> str:
    """A distinct made-up word per number (base 26, 4 letters)."""
    return "".join(chr(97 + (n // 26**k) % 26) for k in range(4))


def filler(i: int) -> str:
    """Unique everyday sentences: real speech rarely repeats verbatim over hours."""
    return f"The {word(i)} and {word(i + 7919)} were {word(i + 15887)} near {word(i + 23869)}."


def long_story(src: str, hours: float) -> list[Sent]:
    """Sentences of 4 s every 5 s; every 5 minutes a premise and a hot payoff."""
    out: list[Sent] = []
    for i in range(int(hours * 3600 / 5)):
        start = i * 5.0
        heat, tags, text = 5.0, (), filler(i)
        k = i % HOT_EVERY
        if k == 25:
            text = f"Watch me try jump number {i // HOT_EVERY} over the river."
        if k == 30:
            heat, tags = 80.0, ("LOUD", "LAUGH")
            text = f"No way, jump {i // HOT_EVERY} landed on the {word(i + 31847)}!"
        if k == 31:
            heat, tags = 40.0, ("LOUD",)
        out.append(Sent(src, i, start, start + 4.0, text, heat, tags))
    return out


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def seed_long(hours: float) -> str:
    sid = uuid.uuid4()
    with get_sessionmaker()() as s:
        s.add(
            Source(
                id=sid,
                platform=Platform.youtube,
                external_id=sid.hex[:11],
                url=f"https://youtu.be/{sid.hex[:11]}",
                title="Marathon stream",
                channel_name="Kai Cenat",
                status=SourceStatus.ready,
                duration_s=hours * 3600,
            )
        )
        tr = Transcript(
            source_id=sid, model="m", device="cpu", language="en", words_path="x", word_count=1
        )
        s.add(tr)
        s.flush()
        s.add_all(
            Segment(
                transcript_id=tr.id,
                idx=st.idx,
                start_s=st.start,
                end_s=st.end,
                text=st.text,
                heat=st.heat,
                tags=[{"type": t} for t in st.tags],
            )
            for st in long_story(str(sid), hours)
        )
        s.commit()
    return str(sid)


def run(client: TestClient, sid: str, **kw: Any) -> dict[str, Any]:
    r = client.post("/api/v1/runs", json={"source_ids": [sid], "pick_mode": "free", **kw})
    assert r.status_code == 201, r.text
    w = Worker("t", caps=("cpu", "net", "ml"))
    for _ in range(5):
        if not w.run_once():
            break
    return client.get(f"/api/v1/runs/{r.json()['id']}").json()


def spans(r: dict[str, Any]) -> list[tuple[float, float]]:
    return sorted((s["parts"][0]["start_s"], s["parts"][0]["end_s"]) for s in r["shorts"])


# ------------------------------------------------------------------ selection
def test_thirty_shorts_from_one_long_video(client: TestClient) -> None:
    sid = seed_long(3)  # 36 hot moments
    r = run(client, sid, n=30)
    assert r["status"] == "succeeded", r.get("error")
    got = spans(r)
    assert len(got) == 30  # the old rule allowed 2 per source
    assert all(a[1] <= b[0] for a, b in itertools.pairwise(got))  # no overlaps
    assert all(15 <= e - s <= 90 for s, e in got)  # "short" preset


def test_long_preset_keeps_whole_scenes(client: TestClient) -> None:
    sid = seed_long(1)
    r = run(client, sid, n=10, length="long")
    assert r["status"] == "succeeded", r.get("error")
    got = spans(r)
    assert len(got) == 10
    assert all(45 <= e - s <= 180 for s, e in got)
    assert max(e - s for s, e in got) > 90  # longer than a classic Short


def test_run_limits(client: TestClient) -> None:
    sid = seed_long(0.2)
    body = {"source_ids": [sid], "pick_mode": "free"}
    assert client.post("/api/v1/runs", json={**body, "n": 50}).status_code == 201
    assert client.post("/api/v1/runs", json={**body, "n": 51}).status_code == 422
    assert client.post("/api/v1/runs", json={**body, "length": "huge"}).status_code == 422


def test_length_presets_shape_candidates() -> None:
    sents = long_story("s", 1)
    for name, lim in LENGTHS.items():
        cands = build_candidates(
            sents, k=20, min_len=lim.min_len, max_len=lim.max_len, min_talk=lim.min_talk
        )
        assert cands, name
        assert all(lim.min_len <= c.end - c.start <= lim.max_len for c in cands), name


def test_prompt_states_the_length() -> None:
    cands = build_candidates(long_story("s", 0.5), k=3)
    msg = select_user_message(cands, n=3, credits={}, topic=None, deep=False, length=(45, 170))
    assert "Each Short should be 45-170 seconds long." in msg


def test_ten_hour_video_is_used_whole_by_default() -> None:
    s = Settings()
    assert default_window(10 * 3600, s.max_source_hours, s.default_window_hours) is None
    assert default_window(13 * 3600, s.max_source_hours, s.default_window_hours) is not None


# ------------------------------------------------------------------ downloads
def test_long_section_rule() -> None:
    assert not is_long_section(None)
    assert not is_long_section(Window(60, 60 + 20 * 60))
    assert is_long_section(Window(0, 2 * 3600))
    assert is_long_section(Window(3600, None))


@needs_ffmpeg
def test_long_audio_part_is_downloaded_whole_then_cut_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    full = make_audio(tmp_path / "full.m4a", 30)
    ranges: list[Any] = []

    def fake_download(
        self: Downloader, url: str, out_dir: Path, stem: str, log: Any, opts: dict[str, Any]
    ) -> Path:
        ranges.append(opts.get("download_ranges"))
        out_dir.mkdir(parents=True, exist_ok=True)
        return Path(shutil.copy(full, out_dir / f"{stem}.m4a"))

    monkeypatch.setattr(Downloader, "_download", fake_download)
    monkeypatch.setattr(downloader, "LONG_SECTION_S", 10)
    out = Downloader().download_audio("https://youtu.be/x", tmp_path / "o", Window(5, 25))
    assert ranges == [None]  # whole-file download, no ffmpeg section
    assert out.name == "audio.m4a" and not (tmp_path / "o" / "audio_full.m4a").exists()
    dur = ffmpeg.probe(out).duration_s
    assert dur is not None and abs(dur - 20) < 0.2

    ranges.clear()
    Downloader().download_audio("https://youtu.be/x", tmp_path / "p", Window(5, 12))
    assert ranges and ranges[0] is not None  # a short part is still a section download
