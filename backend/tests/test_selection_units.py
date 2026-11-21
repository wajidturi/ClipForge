from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from clipforge.ai.base import AIError, Usage
from clipforge.ai.ollama import OllamaProvider
from clipforge.ai.prompts import AIPick, AIPickList, select_user_message
from clipforge.pipeline.selection import Pick, Sent
from clipforge.pipeline.selection.ai_picker import ai_picks
from clipforge.pipeline.selection.callbacks import find_callbacks
from clipforge.pipeline.selection.evaluate import Range, evaluate
from clipforge.pipeline.selection.heuristic import heuristic_picks, keywords
from clipforge.pipeline.selection.validate import clean_hashtags, clean_hook, snap, validate
from clipforge.pipeline.selection.windows import build_candidates, window_score

SRC = "src-1"


def filler(i: int) -> str:
    """Distinct everyday words per sentence (real speech rarely repeats verbatim)."""
    word = lambda k: "".join(chr(97 + (i * 7 + k * 3 + j * 5) % 26) for j in range(5))  # noqa: E731
    return f"So the {word(1)} and {word(2)} were {word(3)} near {word(4)}."


def story(offset: float = 0.0, src: str = SRC, peak_heat: float = 80.0) -> list[Sent]:
    """60 sentences of 4 s each (1 s gaps). Hot payoff at sentence 30 (bridge jump),
    a second, smaller one at 45 (police chase)."""
    out = []
    for i in range(60):
        start = offset + i * 5.0
        heat, tags, text = 5.0, (), filler(i)
        if i == 28:
            text = "Watch me jump the bridge with the red car."
        if i == 30:
            heat, tags, text = peak_heat, ("LOUD", "LAUGH"), "The car flew over the bridge, ha ha!"
        if i == 31:
            heat, tags = 40.0, ("LOUD",)
        if i == 43:
            text = "The police helicopter is following us now."
        if i == 45:
            heat, tags, text = 65.0, ("CHAT",), "They crashed the helicopter into the tower!"
        out.append(Sent(src, i, start, start + 4.0, text, heat, tags))
    return out


# ------------------------------------------------------------------ windows
def test_candidates_cover_the_peak_with_a_premise() -> None:
    sents = story()
    cands = build_candidates(sents, k=5)
    best = cands[0]
    assert best.id == 1 and best.source_id == SRC
    assert best.start <= 150 <= best.end  # sentence 30 starts at 150 s
    assert 15 <= best.duration <= 60
    assert (best.peak - best.start) / best.duration >= 0.4  # payoff in the back half
    assert set(best.tags) == {"LAUGH", "LOUD"}
    # candidates never overlap each other
    for a in cands:
        for b in cands:
            if a is not b:
                assert a.end <= b.start or b.end <= a.start


def test_candidates_skip_used_ranges() -> None:
    cands = build_candidates(story(), k=5, exclude=[(120.0, 200.0)])
    assert all(c.end <= 120 or c.start >= 200 for c in cands)


def test_window_score_penalties() -> None:
    good = [Sent(SRC, 0, 0, 6, "The red car is fast.", 10), Sent(SRC, 1, 7, 13, "It crashed!", 80)]
    bad = [Sent(SRC, 0, 0, 6, "And then it crashed!", 80), Sent(SRC, 1, 7, 13, "Okay.", 10)]
    assert window_score(good, min_talk=12) > window_score(bad, min_talk=12) + 15
    assert window_score([Sent(SRC, 0, 0, 5, "x", 0)], min_talk=1) == 0


# ------------------------------------------------------------------ validation
def test_snap_to_whole_sentences() -> None:
    sents = story()
    assert snap(sents, 151.0, 162.0) == (30, 32)  # mid-sentence -> whole sentences
    assert snap(sents, 149.5, 170.0) == (30, 33)  # in a gap -> next sentence
    assert snap(sents, 10, 5) is None


def mk(start: float, end: float, src: str = SRC, hook: str = "big jump", **kw: Any) -> Pick:
    return Pick(src, start, end, hook, kw.get("title", "t"), kw.get("tags", []), [], None, 50, "r")


def test_validate_rules() -> None:
    sents = {SRC: story(), "s2": story(src="s2")}
    picks = [
        mk(130, 165, hook="the car flew over the bridge wow amazing"),  # ok, hook trimmed
        mk(140, 170),  # overlaps the first
        mk(10, 16),  # too little speech
        mk(200, 240),  # ok
        mk(250, 290),  # third from SRC: over the per-source cap
        mk(0, 200, src="s2"),  # too long
    ]
    ok, bad = validate(picks, sents, n=5, used={})
    # 165 is where sentence 33 *starts*, so the pick ends after sentence 32 (164 s)
    assert [(p.start, p.end) for p in ok] == [(130.0, 164.0), (200.0, 239.0)]
    assert ok[0].hook == "THE CAR FLEW OVER THE BRIDGE"
    reasons = {(p.start, p.end): " ".join(p.issues) for p in bad}
    assert "overlaps" in reasons[(140.0, 169.0)]
    assert "TOO SHORT" in reasons[(10.0, 19.0)]
    assert "already 2" in reasons[(250.0, 289.0)]
    assert "TOO LONG" in reasons[(0.0, 199.0)]


def test_validate_respects_used_ranges_and_n() -> None:
    ok, bad = validate(
        [mk(130, 165), mk(200, 240)], {SRC: story()}, n=1, used={SRC: [(100.0, 140.0)]}
    )
    assert ok == [] or ok[0].start >= 140
    assert any("already used" in " ".join(p.issues) for p in bad)


def test_text_cleaning() -> None:
    assert clean_hook('"speed found kfc in gta six today."') == "SPEED FOUND KFC IN GTA SIX"
    assert clean_hashtags(["#GTA6", "gta6", "Kai Cenat", "", "a", "b", "c"]) == [
        "#gta6",
        "#kaicenat",
        "#a",
        "#b",
        "#c",
    ]
    assert clean_hashtags([]) == ["#shorts"]


# ------------------------------------------------------------------ heuristic
def test_heuristic_picks_caps_and_dedupes() -> None:
    sents = story() + story(offset=1000, src="s2", peak_heat=70)
    cands = build_candidates(sents[:60], k=10) + build_candidates(sents[60:], k=10, start_id=11)
    picks = heuristic_picks(cands, n=5, credit_for={SRC: "Kai Cenat", "s2": None})
    per = {}
    for p in picks:
        per[p.source_id] = per.get(p.source_id, 0) + 1
    assert max(per.values()) <= 2
    top = picks[0]
    assert (
        top.credit == "Kai Cenat"
        and top.hook.startswith("Kai ")
        and top.title.startswith("Kai Cenat:")
    )
    assert top.keywords and all(k.isupper() for k in top.keywords)
    assert keywords("the bridge the bridge car") == ["BRIDGE", "CAR"]


# ------------------------------------------------------------------ callbacks
def test_callback_pair_found() -> None:
    sents = [
        Sent(SRC, 0, 100, 104, "I bet I can jump the bridge with this car.", 10),
        Sent(SRC, 1, 110, 114, "Let's drive.", 5),
        Sent(SRC, 2, 2500, 2504, "The bridge! I actually made it!", 85),
        Sent(SRC, 3, 140, 144, "The bridge is close.", 90),  # too soon after the claim
    ]
    pairs = find_callbacks(sorted(sents, key=lambda s: s.start))
    assert len(pairs) == 1 and pairs[0].payoff.start == 2500 and "bridge" in pairs[0].shared


# ------------------------------------------------------------------ eval harness
def test_eval_precision_recall() -> None:
    labels = [Range("a", 100, 130), Range("a", 500, 520), Range("b", 10, 40)]
    picks = [Range("a", 105, 135), Range("a", 300, 330), Range("b", 12, 38), Range("b", 14, 36)]
    r = evaluate(picks, labels)
    assert (r.hits, r.picks, r.labels) == (2, 4, 3)  # the duplicate b pick does not count twice
    assert r.precision == 0.5 and r.recall == pytest.approx(2 / 3)


# ------------------------------------------------------------------ AI picker
class FakeProvider:
    name, model = "fake", "fake-1"

    def __init__(self, answer: AIPickList | Exception) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def complete_json(self, system: str, user: str, schema: Any, *, timeout: float) -> Any:
        self.prompts.append(user)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer, Usage("fake", "fake-1", 100, 20, 1.0, 1)

    def health(self) -> tuple[bool, str]:
        return True, "ok"


def test_ai_picks_trusts_ids_only_and_clamps() -> None:
    cands = build_candidates(story(), k=3)
    c = cands[0]
    answer = AIPickList(
        picks=[
            AIPick(
                candidate_id=c.id,
                start=c.start - 100,
                end=c.end + 3,
                hook="BRIDGE JUMP",
                title="t",
                score=0,
            ),
            AIPick(candidate_id=99, hook="X", title="y"),
            AIPick(candidate_id=c.id, hook="dup", title="dup"),
        ]
    )
    picks, usage, notes = ai_picks(FakeProvider(answer), cands, n=2, credits={SRC: "Kai"})
    assert len(picks) == 1 and notes == ["AI chose unknown candidate 99; ignored"]
    p = picks[0]
    assert p.start == c.start - 10 and p.end == c.end + 3  # nudge limited to 10 s
    assert p.score == c.score  # model said 0 -> signal score
    assert usage.input_tokens == 100


def test_prompt_wraps_transcript_as_data() -> None:
    cands = build_candidates(story(), k=2)
    msg = select_user_message(cands, n=1, credits={SRC: "Kai"}, topic="GTA 6", deep=False)
    assert "Topic to prefer: GTA 6." in msg and msg.count("<transcript>") == len(cands)
    assert "creator: Kai" in msg


# ------------------------------------------------------------------ Ollama client
def ollama(responses: list[Any], seen: list[dict[str, Any]] | None = None) -> OllamaProvider:
    seq = iter(responses)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})
        if seen is not None:
            seen.append(json.loads(req.content))
        status, content = next(seq)
        if status != 200:
            return httpx.Response(status, text=content)
        return httpx.Response(
            200, json={"message": {"content": content}, "prompt_eval_count": 50, "eval_count": 10}
        )

    return OllamaProvider("qwen3.5:4b", transport=httpx.MockTransport(handler))


GOOD = json.dumps({"picks": [{"candidate_id": 1, "hook": "BRIDGE JUMP", "title": "t"}]})


def test_ollama_returns_validated_json_and_sends_schema() -> None:
    seen: list[dict[str, Any]] = []
    out, usage = ollama([(200, GOOD)], seen).complete_json("s", "u", AIPickList, timeout=5)
    assert out.picks[0].hook == "BRIDGE JUMP" and usage.calls == 1 and usage.output_tokens == 10
    body = seen[0]
    assert body["think"] is False and body["stream"] is False
    assert body["format"]["required"] == ["picks"]


def test_ollama_repairs_bad_json_once() -> None:
    seen: list[dict[str, Any]] = []
    out, usage = ollama([(200, '{"picks": [{"hook": 1}]}'), (200, GOOD)], seen).complete_json(
        "s", "u", AIPickList, timeout=5
    )
    assert out.picks[0].candidate_id == 1 and usage.calls == 2
    assert "did not match the schema" in seen[1]["messages"][-1]["content"]
    with pytest.raises(AIError, match="invalid JSON twice"):
        ollama([(200, "nope"), (200, "still nope")]).complete_json("s", "u", AIPickList, timeout=5)


def test_ollama_errors_are_readable() -> None:
    with pytest.raises(AIError, match="ollama pull"):
        ollama([(404, 'model "x" not found')]).complete_json("s", "u", AIPickList, timeout=5)
    ok, detail = ollama([]).health()
    assert ok and "qwen3.5:4b" in detail
    missing = OllamaProvider("llama9:70b", transport=ollama([]).transport)
    assert missing.health() == (
        False,
        "Model 'llama9:70b' is not installed. Run: ollama pull llama9:70b",
    )
    down = OllamaProvider("m", url="http://127.0.0.1:9")
    assert down.health()[0] is False
