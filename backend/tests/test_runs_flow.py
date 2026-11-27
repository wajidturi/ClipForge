"""Runs end to end through the API and a worker (sources are seeded as analysed)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from clipforge.ai.base import AIError
from clipforge.ai.prompts import AIPick, AIPickList
from clipforge.api.app import create_app
from clipforge.core.config import get_settings
from clipforge.db.enums import AssetKind, AssetOwner, Platform, SourceStatus
from clipforge.db.models import MediaAsset, Segment, Source, Transcript
from clipforge.db.session import get_sessionmaker
from clipforge.jobs.worker import Worker
from clipforge.services import runs as runs_svc

from .media import make_video, needs_ffmpeg
from .test_selection_units import FakeProvider, story


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def seed_source(title: str = "Stream", channel: str | None = "Kai Cenat", **src_kw: Any) -> str:
    sid = uuid.uuid4()
    with get_sessionmaker()() as s:
        s.add(
            Source(
                id=sid,
                platform=Platform.youtube,
                external_id=sid.hex[:11],
                url=f"https://youtu.be/{sid.hex[:11]}",
                title=title,
                channel_name=channel,
                status=src_kw.get("status", SourceStatus.ready),
                duration_s=300,
            )
        )
        tr = Transcript(
            source_id=sid, model="m", device="cpu", language="en", words_path="x", word_count=600
        )
        s.add(tr)
        s.flush()
        for st in story(src=str(sid)):
            s.add(
                Segment(
                    transcript_id=tr.id,
                    idx=st.idx,
                    start_s=st.start,
                    end_s=st.end,
                    text=st.text,
                    heat=st.heat,
                    tags=[{"type": t} for t in st.tags],
                )
            )
        s.commit()
    return str(sid)


def run_jobs() -> None:
    w = Worker("t", caps=("cpu", "net", "ml"))
    for _ in range(5):
        if not w.run_once():
            return


def start(client: TestClient, sources: list[str], **kw: Any) -> dict[str, Any]:
    r = client.post("/api/v1/runs", json={"source_ids": sources, **kw})
    assert r.status_code == 201, r.text
    run_jobs()
    return client.get(f"/api/v1/runs/{r.json()['id']}").json()


def test_free_run_picks_whole_sentence_moments(client: TestClient) -> None:
    sid = seed_source()
    run = start(client, [sid], n=2, pick_mode="free")
    assert run["status"] == "succeeded" and run["ai_provider"] is None
    assert len(run["shorts"]) == 2 and run["candidates"]
    top = run["shorts"][0]
    part = top["parts"][0]
    assert part["start_s"] <= 150 <= part["end_s"]  # contains the hot sentence
    assert part["start_s"] % 5 == 0 and part["end_s"] % 5 == 4  # sentence boundaries
    assert top["hook"].isupper() and top["title"].startswith("Kai Cenat:")
    assert "#shorts" in top["hashtags"] and top["credit"] == "Kai Cenat"
    assert run["result"]["picked"] == 2


def test_smart_run_uses_ai_text(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sid = seed_source()
    answer = AIPickList(
        picks=[
            AIPick(
                candidate_id=1,
                hook="kai jumps the bridge",
                title="Kai Cenat jumps the bridge",
                hashtags=["gta6", "kaicenat"],
                keywords=["bridge"],
                score=88,
                reason="clear payoff",
            )
        ]
    )
    fake = FakeProvider(answer)
    monkeypatch.setattr(runs_svc, "make_provider", lambda settings, model=None: fake)
    run = start(client, [sid], n=1, pick_mode="smart", topic="GTA 6")
    assert run["ai_provider"] == "ollama" and run["ai_model"] == get_settings().ollama_model
    [short] = run["shorts"]
    assert short["hook"] == "KAI JUMPS THE BRIDGE" and short["score"] == 88
    assert short["hashtags"] == ["#gta6", "#kaicenat", "#shorts"] and short["keywords"] == [
        "BRIDGE"
    ]
    assert "Topic to prefer: GTA 6." in fake.prompts[0]
    assert run["ai_usage"]["input_tokens"] == 100


def test_ai_failure_falls_back_and_says_so(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = seed_source()
    fake = FakeProvider(AIError("Ollama is not reachable"))
    monkeypatch.setattr(runs_svc, "make_provider", lambda settings, model=None: fake)
    run = start(client, [sid], n=2, pick_mode="smart")
    assert run["status"] == "succeeded" and len(run["shorts"]) == 2
    assert any("AI unavailable" in w for w in run["result"]["warnings"])


def test_ai_picking_too_few_is_topped_up(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = seed_source()
    fake = FakeProvider(AIPickList(picks=[AIPick(candidate_id=1, hook="ONE", title="one")]))
    monkeypatch.setattr(runs_svc, "make_provider", lambda settings, model=None: fake)
    run = start(client, [sid], n=2, pick_mode="smart")
    assert len(run["shorts"]) == 2
    assert any("added by signal score" in w for w in run["result"]["warnings"])
    assert sum(s["ai_reason"].startswith("filled by signal score") for s in run["shorts"]) == 1


def test_second_run_avoids_used_moments_and_drop_frees_them(client: TestClient) -> None:
    sid = seed_source()
    first = start(client, [sid], n=1, pick_mode="free")
    a = first["shorts"][0]["parts"][0]
    second = start(client, [sid], n=1, pick_mode="free")
    b = second["shorts"][0]["parts"][0]
    assert b["end_s"] <= a["start_s"] or b["start_s"] >= a["end_s"]
    assert client.delete(f"/api/v1/shorts/{first['shorts'][0]['id']}").status_code == 204
    assert client.get(f"/api/v1/runs/{first['id']}").json()["shorts"] == []
    third = start(client, [sid], n=1, pick_mode="free")
    assert (
        third["shorts"][0]["parts"][0]["start_s"] == a["start_s"]
    )  # the freed best moment is back


def test_edit_pick_cleans_text_and_snaps_times(client: TestClient) -> None:
    sid = seed_source()
    short = start(client, [sid], n=1, pick_mode="free")["shorts"][0]
    r = client.patch(
        f"/api/v1/shorts/{short['id']}",
        json={
            "hook": "this is a very long hook with many words",
            "start_s": 141.5,
            "end_s": 172.2,
            "hashtags": ["GTA6"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hook"] == "THIS IS A VERY LONG HOOK"
    assert (body["parts"][0]["start_s"], body["parts"][0]["end_s"]) == (140.0, 174.0)
    assert body["hashtags"] == ["#gta6", "#shorts"]
    bad = client.patch(f"/api/v1/shorts/{short['id']}", json={"start_s": 50, "end_s": 40})
    assert bad.status_code == 422


def test_run_input_errors(client: TestClient) -> None:
    pending = seed_source(status=SourceStatus.analyzing)
    r = client.post("/api/v1/runs", json={"source_ids": [pending], "n": 1})
    assert r.status_code == 422 and "not analysed" in r.json()["detail"]
    assert client.post("/api/v1/runs", json={"source_ids": [str(uuid.uuid4())]}).status_code == 422
    assert client.post("/api/v1/runs", json={"source_ids": []}).status_code == 422
    assert client.post("/api/v1/runs", json={"source_ids": [pending], "n": 99}).status_code == 422


def test_run_listing_and_ai_status_without_ai(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CF_AI_PROVIDER", "none")
    get_settings.cache_clear()
    sid = seed_source()
    run = start(client, [sid], n=1, pick_mode="smart")  # AI off -> heuristic
    assert run["ai_provider"] is None and len(run["shorts"]) == 1
    assert [r["id"] for r in client.get("/api/v1/runs").json()] == [run["id"]]
    st = client.get("/api/v1/ai/status").json()
    assert st["provider"] == "none" and st["ok"]


@needs_ffmpeg
def test_preview_strip_from_video(client: TestClient, tmp_path: Path) -> None:
    sid = seed_source()
    data = get_settings().resolved_data_dir
    video = make_video(data / "v.mp4", 300)
    with get_sessionmaker()() as s:
        s.add(
            MediaAsset(
                owner_type=AssetOwner.source,
                owner_id=uuid.UUID(sid),
                kind=AssetKind.video,
                path=video.relative_to(data).as_posix(),
            )
        )
        s.commit()
    short = start(client, [sid], n=1, pick_mode="free")["shorts"][0]
    assert short["has_preview"] is True
    r = client.get(f"/api/v1/shorts/{short['id']}/preview.jpg")
    assert (
        r.status_code == 200
        and r.headers["content-type"] == "image/jpeg"
        and r.content[:2] == b"\xff\xd8"
    )
    other = start(client, [seed_source()], n=1, pick_mode="free")["shorts"][0]
    assert other["has_preview"] is False
    assert client.get(f"/api/v1/shorts/{other['id']}/preview.jpg").status_code == 404


def test_time_range_limits_where_moments_come_from(client: TestClient) -> None:
    """Pick only from 1:30 to 4:00 of a 5-minute source."""
    sid = seed_source()
    run = start(client, [sid], n=2, pick_mode="free", start="1:30", end="4:00")
    assert run["status"] == "succeeded" and run["params"]["range"] == [90.0, 240.0]
    assert run["shorts"]
    for short in run["shorts"]:
        part = short["parts"][0]
        assert part["start_s"] >= 90 and part["end_s"] <= 240


def test_time_range_errors(client: TestClient) -> None:
    sid = seed_source()  # 300 s long
    bad = client.post("/api/v1/runs", json={"source_ids": [sid], "start": "11:00", "end": "5:00"})
    assert bad.status_code == 422 and "after the start" in bad.json()["detail"]
    late = client.post("/api/v1/runs", json={"source_ids": [sid], "start": "10:00"})
    assert late.status_code == 422 and "outside" in late.json()["detail"]
    nonsense = client.post("/api/v1/runs", json={"source_ids": [sid], "start": "abc"})
    assert nonsense.status_code == 422


def test_a_calm_range_still_gives_moments(client: TestClient) -> None:
    """Real bug: 55:00-58:00 of a stream had no excitement peaks, so nothing was picked.
    A range the user chose themselves is used even when it is calm."""
    sid = seed_source()
    run = start(client, [sid], n=1, pick_mode="free", start="0:00", end="1:20")
    assert run["status"] == "succeeded", run["error"]
    part = run["shorts"][0]["parts"][0]
    assert part["end_s"] <= 80
