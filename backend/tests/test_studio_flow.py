"""Phase 6: settings, library, review, export, stats, studio words and AI edit."""

from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from clipforge.ai.base import Usage
from clipforge.core.config import get_settings
from clipforge.db.enums import (
    AssetKind,
    AssetOwner,
    EditStatus,
    Platform,
    QcVerdict,
    ShortStatus,
    VersionOrigin,
    VersionStatus,
)
from clipforge.db.models import (
    EditRequest,
    Job,
    MediaAsset,
    QcReport,
    Short,
    ShortVersion,
    Source,
)
from clipforge.db.session import get_sessionmaker
from clipforge.services import ai_edit, settings_store
from clipforge.services import render as render_svc

from .media import needs_ffmpeg
from .test_render_flow import client, media_path, offline_faces, render, run_jobs, seed_short
from .test_runs_flow import seed_source, start

__all__ = ["client", "offline_faces"]  # fixtures used by name


def fake_render(short_id: str, verdict: QcVerdict = QcVerdict.pass_, no: int = 1) -> str:
    """A ready version with small stand-in files (no FFmpeg): fast library/export tests."""
    root = get_settings().resolved_data_dir
    with get_sessionmaker()() as s:
        short = s.get(Short, uuid.UUID(short_id))
        assert short is not None
        ver = ShortVersion(
            short_id=short.id,
            version_no=no,
            origin=VersionOrigin.render,
            settings={"style": "classic", "layout": "auto", "layout_used": "crop"},
            status=VersionStatus.ready,
            caption_overrides={},
        )
        s.add(ver)
        s.flush()
        folder = root / "renders" / short_id / f"v{no}"
        folder.mkdir(parents=True, exist_ok=True)
        for kind, name, data in (
            (AssetKind.mp4, "final.mp4", b"\x00\x00\x00\x18ftypmp42"),
            (AssetKind.cover, "cover.jpg", b"\xff\xd8\xff\xe0cover"),
        ):
            (folder / name).write_bytes(data)
            s.add(
                MediaAsset(
                    owner_type=AssetOwner.short_version,
                    owner_id=ver.id,
                    kind=kind,
                    path=(folder / name).relative_to(root).as_posix(),
                    bytes=len(data),
                    duration_s=20.0 if kind == AssetKind.mp4 else None,
                )
            )
        s.add(QcReport(short_version_id=ver.id, verdict=verdict, checks={}, reasons=[]))
        short.active_version_id = ver.id
        short.status = ShortStatus.review
        s.commit()
        return str(ver.id)


def set_source(short_id: str, **values: Any) -> None:
    with get_sessionmaker()() as s:
        short = s.get(Short, uuid.UUID(short_id))
        assert short is not None
        src = s.get(Source, short.source_id)
        assert src is not None
        for k, v in values.items():
            setattr(src, k, v)
        s.commit()


def jobs_for(short_id: str) -> list[Job]:
    with get_sessionmaker()() as s:
        return list(
            s.scalars(select(Job).where(Job.subject_id == uuid.UUID(short_id)).order_by(Job.id))
        )


# ------------------------------------------------------------------ settings
def test_settings_list_save_validate_and_reset(client: TestClient) -> None:
    fields = {f["key"]: f for f in client.get("/api/v1/settings").json()["fields"]}
    assert fields["ai_provider"]["kind"] == "choice" and "none" in fields["ai_provider"]["choices"]
    assert fields["candidates_k"]["min"] == 5 and fields["candidates_k"]["max"] == 120
    assert fields["render_style"]["choices"][0] == "classic"
    assert fields["render_aspects"]["kind"] == "list"
    assert fields["whisper_model"]["nullable"] and not fields["ollama_model"]["overridden"]
    assert "database_url" not in fields and "secret_key" not in fields  # never editable

    r = client.patch(
        "/api/v1/settings",
        json={
            "values": {"ollama_model": " llama3.2:3b ", "render_style": "box", "candidates_k": 40}
        },
    )
    assert r.status_code == 200, r.text
    got = {f["key"]: f for f in r.json()["fields"]}
    assert got["ollama_model"]["value"] == "llama3.2:3b" and got["ollama_model"]["overridden"]
    assert got["ollama_model"]["default"] == "qwen3.5:4b"
    eff = settings_store.effective()
    assert (eff.render_style, eff.candidates_k) == ("box", 40)
    assert render_svc.defaults()["style"] == "box"

    bad = client.patch("/api/v1/settings", json={"values": {"candidates_k": 1, "ai_timeout_s": 5}})
    assert bad.status_code == 422 and bad.json()["detail"]["key"] == "candidates_k"
    assert settings_store.effective().ai_timeout_s == 300  # all-or-nothing
    assert client.patch("/api/v1/settings", json={"values": {"port": 1}}).status_code == 422
    assert (
        client.patch("/api/v1/settings", json={"values": {"render_style": "nope"}}).status_code
        == 422
    )

    r = client.patch("/api/v1/settings", json={"reset": ["ollama_model"]})
    got = {f["key"]: f for f in r.json()["fields"]}
    assert got["ollama_model"]["value"] == "qwen3.5:4b" and not got["ollama_model"]["overridden"]


def test_saved_ai_provider_applies_to_new_runs(client: TestClient) -> None:
    client.patch("/api/v1/settings", json={"values": {"ai_provider": "none"}})
    assert client.get("/api/v1/ai/status").json()["provider"] == "none"
    run = start(client, [seed_source()], n=1, pick_mode="smart")
    assert run["status"] == "succeeded" and run["ai_provider"] is None


def test_auto_render_queues_renders_when_a_run_finishes(client: TestClient) -> None:
    client.patch("/api/v1/settings", json={"values": {"auto_render": True}})
    r = client.post(
        "/api/v1/runs", json={"source_ids": [seed_source()], "n": 2, "pick_mode": "free"}
    )
    w_run = r.json()["id"]
    from clipforge.jobs.worker import Worker

    Worker("t", caps=("cpu",)).run_once()  # only the picking job (renders need net too)
    shorts = client.get(f"/api/v1/runs/{w_run}").json()["shorts"]
    assert shorts and all(s["status"] == "rendering" for s in shorts)
    assert all(s["render_job_id"] for s in shorts)


# ------------------------------------------------------------------ library & review
def test_library_filters_search_and_pages(client: TestClient) -> None:
    run = start(
        client,
        [seed_source(title="Big Stream"), seed_source(title="Big Stream")],
        n=3,
        pick_mode="free",
    )
    ids = [s["id"] for s in run["shorts"]]
    assert len(ids) == 3
    fake_render(ids[0])
    fake_render(ids[1], verdict=QcVerdict.warn)
    client.delete(f"/api/v1/shorts/{ids[2]}")

    page = client.get("/api/v1/shorts").json()
    assert page["total"] == 2 and {s["id"] for s in page["items"]} == set(ids[:2])
    assert page["items"][0]["source_title"] == "Big Stream"
    assert client.get("/api/v1/shorts", params={"status": "dropped"}).json()["total"] == 1
    assert [
        s["id"] for s in client.get("/api/v1/shorts", params={"qc": "warn"}).json()["items"]
    ] == [ids[1]]
    hook = run["shorts"][0]["hook"]
    found = client.get("/api/v1/shorts", params={"q": hook.split()[0].lower()}).json()
    assert ids[0] in {s["id"] for s in found["items"]}
    assert client.get("/api/v1/shorts", params={"run_id": str(uuid.uuid4())}).json()["total"] == 0

    p1 = client.get("/api/v1/shorts", params={"limit": 1}).json()
    p2 = client.get("/api/v1/shorts", params={"limit": 1, "cursor": p1["next_cursor"]}).json()
    assert p1["next_cursor"] and p2["next_cursor"] is None
    assert p1["items"][0]["id"] != p2["items"][0]["id"]


def test_review_actions_and_bulk(client: TestClient) -> None:
    run = start(client, [seed_source(), seed_source()], n=3, pick_mode="free")
    a, b, c = (s["id"] for s in run["shorts"])
    r = client.post(f"/api/v1/shorts/{a}/review", json={"action": "approve"})
    assert r.status_code == 409 and "render" in r.json()["detail"]  # not rendered yet
    fake_render(a)
    fake_render(b)
    assert (
        client.post(f"/api/v1/shorts/{a}/review", json={"action": "approve"}).json()["status"]
        == "approved"
    )
    rej = client.post(f"/api/v1/shorts/{b}/review", json={"action": "reject", "reason": "boring"})
    assert rej.json()["status"] == "rejected" and rej.json()["reject_reason"] == "boring"
    reopened = client.post(f"/api/v1/shorts/{b}/review", json={"action": "reopen"}).json()
    assert reopened["status"] == "review" and reopened["reject_reason"] is None

    bulk = client.post(
        "/api/v1/shorts/review",
        json={"action": "approve", "short_ids": [b, c, str(uuid.uuid4())]},
    ).json()
    assert bulk["updated"] == [b]
    assert {x["reason"] for x in bulk["skipped"]} >= {"not found"}

    stats = client.get("/api/v1/stats").json()
    assert stats["shorts"]["approved"] == 2 and stats["shorts"]["picked"] == 1
    assert stats["qc"]["pass"] == 2 and stats["runs"] == 1 and stats["sources_ready"] == 2


def test_edit_after_render_and_not_while_rendering(client: TestClient) -> None:
    run = start(client, [seed_source()], n=1, pick_mode="free")
    sid = run["shorts"][0]["id"]
    fake_render(sid)
    r = client.patch(
        f"/api/v1/shorts/{sid}", json={"hook": "new hook here", "keywords": ["a", "b"]}
    )
    assert r.status_code == 200 and r.json()["hook"] == "NEW HOOK HERE"
    with get_sessionmaker()() as s:
        s.get(Short, uuid.UUID(sid)).status = ShortStatus.rendering  # type: ignore[union-attr]
        s.commit()
    assert client.patch(f"/api/v1/shorts/{sid}", json={"hook": "x"}).status_code == 409


# ------------------------------------------------------------------ export
def test_export_single_and_run_zip(client: TestClient) -> None:
    run = start(client, [seed_source(channel="Some Streamer")], n=2, pick_mode="free")
    a, b = (s["id"] for s in run["shorts"])
    assert client.get(f"/api/v1/shorts/{a}/export.zip").status_code == 409  # nothing rendered
    fake_render(a)
    fake_render(b)

    r = client.get(f"/api/v1/shorts/{a}/export.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(z.namelist()) == ["cover.jpg", "post.txt", "short.mp4"]
    post = z.read("post.txt").decode()
    assert "HASHTAGS" in post and "#shorts" in post and "Some Streamer" in post
    assert "youtu.be/" in post and "t=" in post  # timestamped link to the original

    assert client.get(f"/api/v1/runs/{run['id']}/export.zip").status_code == 409  # none approved
    client.post(f"/api/v1/shorts/{a}/review", json={"action": "approve"})
    z1 = zipfile.ZipFile(io.BytesIO(client.get(f"/api/v1/runs/{run['id']}/export.zip").content))
    assert len([n for n in z1.namelist() if n.endswith("short.mp4")]) == 1
    z2 = zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/v1/runs/{run['id']}/export.zip?only=rendered").content)
    )
    names = z2.namelist()
    assert len([n for n in names if n.endswith("short.mp4")]) == 2 and "shorts.csv" in names
    assert z2.read("shorts.csv").decode().count("\n") == 3  # header + 2 rows
    # temp files are cleaned up after sending
    assert not list((get_settings().resolved_data_dir / "tmp" / "exports").glob("*.zip"))


def test_link_at_handles_platforms() -> None:
    from clipforge.services.export import link_at

    yt = Source(platform=Platform.youtube, url="https://www.youtube.com/watch?v=abc&t=5s")
    assert link_at(yt, 125.7) == "https://www.youtube.com/watch?v=abc&t=125s"
    tw = Source(platform=Platform.twitch, url="https://www.twitch.tv/videos/1")
    assert link_at(tw, 3725) == "https://www.twitch.tv/videos/1?t=1h2m5s"
    assert link_at(Source(platform=Platform.file, url="file:x"), 1) == ""


# ------------------------------------------------------------------ studio
def test_words_view_lists_range_words_and_context(client: TestClient) -> None:
    sid = seed_short()  # words every 0.5 s, Short = 10..30 s
    w = client.get(f"/api/v1/shorts/{sid}/words").json()
    assert w["start_s"] == 10 and w["end_s"] == 30
    assert w["words"][0]["key"] == "10.00" and w["words"][0]["text"] == "word18"
    assert all(10 <= x["start"] < 30 for x in w["words"])
    inside = [s for s in w["sentences"] if s["inside"]]
    assert inside and len(inside) < len(w["sentences"])  # context around the range too


def test_rule_based_edit_plan_and_apply(client: TestClient) -> None:
    client.patch("/api/v1/settings", json={"values": {"ai_provider": "none"}})
    sid = seed_short()
    fake_render(sid)
    r = client.post(
        f"/api/v1/shorts/{sid}/ai-edit",
        json={"instruction": "use the box style and start 3s later"},
    )
    plan = r.json()
    assert r.status_code == 200 and plan["status"] == "planned", plan
    ops = {o["op"]: o for o in plan["plan"]["ops"]}
    assert ops["set_style"]["style"] == "box" and ops["trim"]["start_delta_s"] == 3

    nonsense = client.post(f"/api/v1/shorts/{sid}/ai-edit", json={"instruction": "make it pop"})
    assert nonsense.json()["status"] == "failed" and "Try e.g." in nonsense.json()["error"]

    applied = client.post(f"/api/v1/edits/{plan['id']}/apply").json()
    assert applied["edit"]["status"] == "applied" and applied["job_id"]
    assert applied["short"]["status"] == "rendering"
    assert applied["short"]["parts"][0]["start_s"] > 10  # snapped to a later sentence
    job = jobs_for(sid)[-1]
    assert job.payload["options"]["style"] == "box"
    assert job.payload["options"]["origin"] == "ai_edit"
    assert job.payload["options"]["edit_id"] == plan["id"]
    assert client.post(f"/api/v1/edits/{plan['id']}/apply").status_code == 409  # only once
    history = client.get(f"/api/v1/shorts/{sid}/edits").json()
    assert [h["status"] for h in history] == ["failed", "applied"]


class EditProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self, plan: ai_edit.EditPlan) -> None:
        self.plan = plan
        self.prompts: list[str] = []

    def complete_json(self, system: str, user: str, schema: Any, *, timeout: float) -> Any:
        self.prompts.append(user)
        return self.plan, Usage("fake", "fake-1", calls=1)

    def health(self) -> tuple[bool, str]:
        return True, "ok"


def test_ai_edit_text_only_needs_no_render_and_bad_ops_are_dropped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = seed_short()
    fake_render(sid)
    prov = EditProvider(
        ai_edit.EditPlan(
            summary="new title",
            ops=[
                ai_edit.EditOp(op="set_title", text="When the car flew"),
                ai_edit.EditOp(op="set_layout", layout="sideways"),  # unknown -> dropped
                ai_edit.EditOp(op="set_hashtags", words=["gta", "#Cars"]),
            ],
        )
    )
    monkeypatch.setattr("clipforge.api.routes_shorts.make_provider", lambda s: prov)
    plan = client.post(f"/api/v1/shorts/{sid}/ai-edit", json={"instruction": "better title"}).json()
    assert "Transcript of the clip" in prov.prompts[0] and "word20" in prov.prompts[0]
    assert [o["op"] for o in plan["plan"]["ops"]] == ["set_title", "set_hashtags"]
    assert "sideways" in plan["plan"]["notes"][0]
    applied = client.post(f"/api/v1/edits/{plan['id']}/apply").json()
    assert applied["job_id"] is None and applied["short"]["status"] == "review"
    assert applied["short"]["title"] == "When the car flew"
    assert applied["short"]["hashtags"] == ["#gta", "#cars", "#shorts"]


@needs_ffmpeg
def test_caption_fixes_reach_the_video_and_survive_rerender(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = seed_short()
    short = render(
        client, sid, caption_overrides={"11.00": "HELLO", "11.50": ""}, origin="manual_edit"
    )
    v1 = short["active"]
    assert short["status"] == "review" and v1["origin"] == "manual_edit"

    def ass_text(version_id: str) -> str:
        with get_sessionmaker()() as s:
            a = s.scalar(
                select(MediaAsset).where(
                    MediaAsset.owner_id == uuid.UUID(version_id),
                    MediaAsset.kind == AssetKind.caption_ass,
                )
            )
            assert a is not None
            return (get_settings().resolved_data_dir / a.path).read_text("utf-8").lower()

    text = ass_text(v1["id"])
    assert "hello" in text and "word21" not in text and "word22" in text
    words = client.get(f"/api/v1/shorts/{sid}/words").json()
    assert words["overrides"] == {"11.00": "HELLO", "11.50": ""}

    # an AI fix_word edit merges with the earlier fixes and links to its new version
    prov = EditProvider(
        ai_edit.EditPlan(
            summary="fix", ops=[ai_edit.EditOp(op="fix_word", wrong="word24", right="Ranger")]
        )
    )
    monkeypatch.setattr("clipforge.api.routes_shorts.make_provider", lambda s: prov)
    plan = client.post(f"/api/v1/shorts/{sid}/ai-edit", json={"instruction": "fix the name"}).json()
    client.post(f"/api/v1/edits/{plan['id']}/apply")
    run_jobs()
    short = client.get(f"/api/v1/shorts/{sid}").json()
    v2 = short["active"]
    assert v2["version_no"] == 2 and v2["origin"] == "ai_edit"
    text2 = ass_text(v2["id"])
    assert "hello" in text2 and "ranger" in text2 and "word24" not in text2
    with get_sessionmaker()() as s:
        er = s.get(EditRequest, uuid.UUID(plan["id"]))
        assert er is not None and er.status == EditStatus.applied
        assert str(er.result_version_id) == v2["id"]
    assert media_path(v2["mp4_asset_id"]).exists()


def test_settings_cache_falls_back_without_tables(tmp_path: Path) -> None:
    settings_store.invalidate()
    eff = settings_store.effective()  # database not migrated in this test
    assert eff.ollama_model == get_settings().ollama_model


def test_explicit_parts_missed_by_the_ai_are_added() -> None:
    ops, notes = ai_edit.merge_explicit(
        "make the hook punchier and use the karaoke style",
        [ai_edit.EditOp(op="set_hook", text="HE FOUND IT")],
        [],
    )
    assert [o.op for o in ops] == ["set_hook", "set_style"] and ops[1].style == "karaoke"
    assert "karaoke" in notes[-1]
    same, _ = ai_edit.merge_explicit(
        "use the box style", [ai_edit.EditOp(op="set_style", style="word")], []
    )
    assert [o.style for o in same] == ["word"]  # the AI's own choice wins


def test_rule_plan_reads_hook_text_and_word_fixes() -> None:
    p = ai_edit.rule_plan("hook: NO WAY HE MADE IT")
    assert [(o.op, o.text) for o in p.ops] == [("set_hook", "NO WAY HE MADE IT")]
    fix = ai_edit.rule_plan("fix Stranger to Ranger")
    assert [(o.op, o.wrong, o.right) for o in fix.ops] == [("fix_word", "Stranger", "Ranger")]


def test_missing_hook_is_written_in_a_focused_second_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = seed_short()
    fake_render(sid)

    class TwoStep(EditProvider):
        def complete_json(self, system: str, user: str, schema: Any, *, timeout: float) -> Any:
            self.prompts.append(system)
            if schema is ai_edit.Rewrite:
                return ai_edit.Rewrite(text="he did not see that coming"), Usage("f", "f", calls=1)
            return self.plan, Usage("f", "f", calls=1)

    prov = TwoStep(
        ai_edit.EditPlan(summary="style", ops=[ai_edit.EditOp(op="set_style", style="karaoke")])
    )
    monkeypatch.setattr("clipforge.api.routes_shorts.make_provider", lambda s: prov)
    plan = client.post(
        f"/api/v1/shorts/{sid}/ai-edit", json={"instruction": "punchier hook, karaoke style"}
    ).json()
    assert len(prov.prompts) == 2 and "banner hook" in prov.prompts[1]
    assert [o["op"] for o in plan["plan"]["ops"]] == ["set_style", "set_hook"]
