"""AI edit: "make the hook punchier", "start 3 seconds later", "use the bold style".

Two steps so nothing changes behind the creator's back:

1. **plan**  - the instruction + the Short's current state + its transcript go to the
   AI, which may only answer with a list of edit operations (strict JSON schema).
   Operations are checked and clamped here; the plan is stored as an EditRequest.
   Without an AI provider a small rule parser understands the common phrases.
2. **apply** - the operations become a field patch (+ caption word fixes) and, if the
   picture changes, a new render (origin ``ai_edit``) that links back to the request.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from clipforge.ai.base import AIError, Provider
from clipforge.db.enums import EditKind, EditStatus
from clipforge.db.models import EditRequest, Job, Short, ShortVersion
from clipforge.pipeline.render import captions, reframe
from clipforge.services import settings_store, versions
from clipforge.services import shorts as shorts_svc

OpName = Literal[
    "trim",
    "set_hook",
    "set_title",
    "set_style",
    "set_layout",
    "set_keywords",
    "set_hashtags",
    "fix_word",
]
MAX_TRIM_S = 30.0


class EditOp(BaseModel):
    """One change. Only the fields that belong to `op` are used."""

    op: OpName
    text: str | None = Field(default=None, description="set_hook / set_title: the new text")
    start_delta_s: float | None = Field(
        default=None, description="trim: + starts later, - starts earlier (seconds)"
    )
    end_delta_s: float | None = Field(
        default=None, description="trim: + ends later, - ends earlier (seconds)"
    )
    style: str | None = Field(default=None, description="set_style: a caption style id")
    layout: str | None = Field(default=None, description="set_layout: a layout id")
    words: list[str] | None = Field(
        default=None, description="set_keywords (1-3 words) / set_hashtags (2-5 tags)"
    )
    wrong: str | None = Field(default=None, description="fix_word: the misheard word")
    right: str | None = Field(default=None, description="fix_word: what it should say")


class EditPlan(BaseModel):
    summary: str = Field(description="one short sentence describing the change")
    ops: list[EditOp] = Field(max_length=8)


SYSTEM = """You edit short vertical videos (YouTube Shorts / TikTok) cut from long streams.
The user describes a change. Reply ONLY with JSON matching the schema: a one-sentence
summary and the smallest list of operations that does what was asked.

Operations:
- trim: move the start/end. start_delta_s > 0 starts later, < 0 earlier;
  end_delta_s > 0 ends later, < 0 ends earlier. Times snap to whole sentences.
- set_hook: the 2-6 word banner shown in the first seconds (UPPERCASE, punchy, no emojis).
- set_title: the post title (max 100 characters).
- set_style: caption style, one of: {styles}.
- set_layout: picture layout, one of: {layouts}.
- set_keywords: 1-3 words highlighted in the captions.
- set_hashtags: 2-5 hashtags.
- fix_word: fix a misheard caption word (wrong -> right).

Rules:
- "Hook" always means the banner TEXT: a request about the hook is a set_hook with new
  wording, never a trim.
- Use trim only when the request is about timing (start, end, longer, shorter, cut, earlier,
  later). Do not trim unless asked.
- One request can need several operations; do each part that was asked, nothing more.
- Never invent facts or names that are not in the transcript; keep the transcript's language.
- If the request is unclear or impossible, return no operations and say why in the summary.

Examples:
"make the hook punchier" -> [{{"op": "set_hook", "text": "HE DID NOT SEE THAT COMING"}}]
"start 2 seconds later and use the bold style" -> [{{"op": "trim", "start_delta_s": 2}},
 {{"op": "set_style", "style": "box"}}]
"it's Ranger not Stranger" -> [{{"op": "fix_word", "wrong": "Stranger", "right": "Ranger"}}]"""


def _context(db: Session, short: Short) -> str:
    view = shorts_svc.words_view(db, short, context_s=20)
    ver = db.get(ShortVersion, short.active_version_id) if short.active_version_id else None
    st = (ver.settings or {}) if ver else {}
    inside = [s for s in view["sentences"] if s["inside"]]
    t0 = view["start_s"]
    lines = [f"[{s['start'] - t0:+.1f}s] {s['text']}" for s in inside]
    before = [s for s in view["sentences"] if s["end"] <= t0][-3:]
    after = [s for s in view["sentences"] if s["start"] >= view["end_s"]][:3]
    return "\n".join(
        [
            f"Length: {view['end_s'] - t0:.1f}s",
            f"Hook: {short.hook or '-'}",
            f"Title: {short.title or '-'}",
            f"Keywords: {', '.join(short.keywords or []) or '-'}",
            f"Hashtags: {' '.join(short.hashtags or []) or '-'}",
            f"Caption style: {st.get('style', '-')}  Layout: {st.get('layout_used', '-')}",
            "",
            "Just before the clip:",
            *[f"[{s['start'] - t0:+.1f}s] {s['text']}" for s in before],
            "",
            "Transcript of the clip (seconds from its start):",
            *lines,
            "",
            "Just after the clip:",
            *[f"[{s['start'] - t0:+.1f}s] {s['text']}" for s in after],
        ]
    )


# ------------------------------------------------------------------ no-AI fallback
_NUM = r"(\d+(?:\.\d+)?)"


def rule_plan(instruction: str) -> EditPlan:
    """Understands the common requests without an AI model."""
    text = instruction.strip()
    low = text.lower()
    ops: list[EditOp] = []
    if m := re.search(r"\bhook\s*(?:to|:|=)\s*[\"']?(.+?)[\"']?\s*$", text, re.I):
        ops.append(EditOp(op="set_hook", text=m.group(1)))
    elif m := re.search(r"\btitle\s*(?:to|:|=)\s*[\"']?(.+?)[\"']?\s*$", text, re.I):
        ops.append(EditOp(op="set_title", text=m.group(1)))
    for sid in captions.STYLES:
        if re.search(rf"\b{re.escape(sid)}\b", low) and "style" in low:
            ops.append(EditOp(op="set_style", style=sid))
            break
    for lay in reframe.LAYOUTS:
        if re.search(rf"\b{lay}\b", low) and "layout" in low:
            ops.append(EditOp(op="set_layout", layout=lay))
            break
    if m := re.search(rf"start\w*\s+{_NUM}\s*s\w*\s+later", low):
        ops.append(EditOp(op="trim", start_delta_s=float(m.group(1))))
    elif m := re.search(rf"start\w*\s+{_NUM}\s*s\w*\s+earlier", low):
        ops.append(EditOp(op="trim", start_delta_s=-float(m.group(1))))
    if m := re.search(rf"end\w*\s+{_NUM}\s*s\w*\s+(earlier|sooner)", low):
        ops.append(EditOp(op="trim", end_delta_s=-float(m.group(1))))
    elif m := re.search(rf"end\w*\s+{_NUM}\s*s\w*\s+later", low):
        ops.append(EditOp(op="trim", end_delta_s=float(m.group(1))))
    elif re.search(r"\b(shorter|tighter|cut it down)\b", low):
        ops.append(EditOp(op="trim", end_delta_s=-5))
    elif re.search(r"\b(longer|more context)\b", low):
        ops.append(EditOp(op="trim", end_delta_s=5))
    fix = re.search(r"[\"']?(\w+)[\"']?\s*(?:->|→|should be|to)\s*[\"']?(\w+)[\"']?", text)
    if fix and not ops and re.search(r"\b(fix|replace|change|spell)\b", low):
        ops.append(EditOp(op="fix_word", wrong=fix.group(1), right=fix.group(2)))
    summary = (
        "; ".join(_describe(o) for o in ops)
        if ops
        else "Not understood without an AI model. Try e.g. 'hook: NO WAY HE DID THAT', "
        "'bold style', 'start 2s later', 'end 3s earlier'."
    )
    return EditPlan(summary=summary, ops=ops)


def _describe(o: EditOp) -> str:
    if o.op == "trim":
        bits = []
        if o.start_delta_s:
            bits.append(
                f"start {abs(o.start_delta_s):g}s {'later' if o.start_delta_s > 0 else 'earlier'}"
            )
        if o.end_delta_s:
            bits.append(
                f"end {abs(o.end_delta_s):g}s {'later' if o.end_delta_s > 0 else 'earlier'}"
            )
        return ", ".join(bits) or "no trim"
    if o.op == "fix_word":
        return f"caption '{o.wrong}' -> '{o.right}'"
    val = o.text or o.style or o.layout or " ".join(o.words or [])
    return f"{o.op.removeprefix('set_')} -> {val}"


# ------------------------------------------------------------------ checks
def sanitize(plan: EditPlan) -> tuple[list[EditOp], list[str]]:
    """Drop operations that cannot be applied; clamp the rest. Returns (ops, notes)."""
    ok: list[EditOp] = []
    notes: list[str] = []
    for o in plan.ops:
        if o.op in ("set_hook", "set_title") and not (o.text or "").strip():
            notes.append(f"{o.op}: empty text ignored")
            continue
        if o.op == "set_style" and o.style not in captions.STYLES:
            notes.append(f"unknown caption style '{o.style}' ignored")
            continue
        if o.op == "set_layout" and o.layout not in reframe.LAYOUTS:
            notes.append(f"unknown layout '{o.layout}' ignored")
            continue
        if o.op in ("set_keywords", "set_hashtags") and not o.words:
            notes.append(f"{o.op}: no words given")
            continue
        if o.op == "fix_word" and not ((o.wrong or "").strip() and o.right is not None):
            notes.append("fix_word needs the wrong and the right word")
            continue
        if o.op == "trim":
            s = max(-MAX_TRIM_S, min(MAX_TRIM_S, o.start_delta_s or 0.0))
            e = max(-MAX_TRIM_S, min(MAX_TRIM_S, o.end_delta_s or 0.0))
            if not s and not e:
                continue
            o = o.model_copy(update={"start_delta_s": s, "end_delta_s": e})
        ok.append(o)
    return ok, notes


class Rewrite(BaseModel):
    text: str = Field(description="the new text only")


REWRITE = {
    "hook": "a NEW banner hook: 2-6 words, UPPERCASE, punchy, no emojis, different from the "
    "current one, true to the transcript",
    "title": "a NEW post title: max 100 characters, curiosity without lying, different from the "
    "current one, true to the transcript",
}


def _rewrite(
    provider: Provider, field: str, short: Short, context: str, instruction: str, timeout: float
) -> tuple[str | None, Any]:
    """One focused call that only writes the hook or the title."""
    current = (short.hook if field == "hook" else short.title) or ""
    out, usage = provider.complete_json(
        f"You write text for short vertical videos. Reply ONLY with JSON: {REWRITE[field]}.",
        f"{context}\n\nThe creator asked: {instruction}\nWrite the new {field}.",
        Rewrite,
        timeout=timeout,
    )
    text = re.sub(r"\s+", " ", out.text).strip().strip("\"'")
    if not text or text.lower() == current.lower():
        return None, usage
    return text, usage


MERGEABLE = ("set_style", "set_layout", "trim")


def merge_explicit(
    instruction: str, ops: list[EditOp], notes: list[str]
) -> tuple[list[EditOp], list[str]]:
    """Small models sometimes do only half of "punchier hook AND karaoke style".

    Anything the rule parser reads unambiguously from the words (a named style or
    layout, "start 2s later") and the AI left out is added, and noted.
    """
    have = {o.op for o in ops}
    extra = [o for o in rule_plan(instruction).ops if o.op in MERGEABLE and o.op not in have]
    if not extra:
        return ops, notes
    more, more_notes = sanitize(EditPlan(summary="", ops=extra))
    return ops + more, notes + more_notes + [
        "Also added from your words: " + "; ".join(_describe(o) for o in more)
    ]


# ------------------------------------------------------------------ plan / apply
def plan(db: Session, short: Short, instruction: str, provider: Provider | None) -> EditRequest:
    if short.status not in shorts_svc.EDITABLE:
        raise shorts_svc.ShortStateError(f"a {short.status.value} Short cannot be edited now")
    instruction = instruction.strip()
    er = EditRequest(
        short_id=short.id,
        base_version_id=short.active_version_id,
        kind=EditKind.ai,
        instruction=instruction[:2000],
        status=EditStatus.pending,
    )
    db.add(er)
    usage: dict[str, Any] = {}
    try:
        if provider is None:
            result = rule_plan(instruction)
            usage = {"provider": "rules"}
        else:
            system = SYSTEM.format(
                styles=", ".join(captions.STYLES), layouts=", ".join(reframe.LAYOUTS)
            )
            user = f"{_context(db, short)}\n\nRequested change: {instruction}"
            timeout = settings_store.effective(db).ai_timeout_s
            result, u = provider.complete_json(system, user, EditPlan, timeout=timeout)
            seconds = u.seconds
            # A "new" hook/title identical to the current one is no change at all.
            same = {"set_hook": short.hook or "", "set_title": short.title or ""}
            result.ops = [
                o
                for o in result.ops
                if not (o.op in same and (o.text or "").strip().lower() == same[o.op].lower())
            ]
            # Small models often skip the text part of a mixed request: ask again for
            # just that field when the words name it and the plan has no such operation.
            for field in ("hook", "title"):
                named = re.search(rf"\b{field}s?\b", instruction, re.I)
                op: OpName = "set_hook" if field == "hook" else "set_title"
                if named and all(o.op != op for o in result.ops):
                    text, u2 = _rewrite(provider, field, short, user, instruction, timeout)
                    seconds += u2.seconds
                    if text:
                        result.ops.append(EditOp(op=op, text=text))
            usage = {"provider": u.provider, "model": u.model, "seconds": round(seconds, 1)}
    except (AIError, shorts_svc.ShortInputError) as e:
        er.status = EditStatus.failed
        er.error = str(e)[:1000]
        db.commit()
        return er
    ops, notes = sanitize(result)
    if provider is not None:
        ops, notes = merge_explicit(instruction, ops, notes)
    er.plan = {
        # what will change, in plain words; the model's own sentence is kept for reference
        "summary": "; ".join(_describe(o) for o in ops)[:300] if ops else result.summary[:300],
        "ai_summary": result.summary[:300],
        "ops": [o.model_dump(exclude_none=True) for o in ops],
        "notes": notes,
        "usage": usage,
    }
    er.status = EditStatus.planned if ops else EditStatus.failed
    if not ops:
        er.error = result.summary[:1000] or "no change was suggested"
    db.commit()
    return er


def _norm(text: str) -> str:
    return re.sub(r"[^\w']", "", text).lower()


def _fix_words(db: Session, short: Short, ops: list[EditOp]) -> dict[str, str]:
    view = shorts_svc.words_view(db, short, context_s=0)
    overrides = dict(view["overrides"])
    for o in ops:
        wrong = _norm(o.wrong or "")
        for w in view["words"]:
            if _norm(w["text"]) == wrong:
                # keep the word's punctuation around the replacement
                lead = re.match(r"^\W*", w["text"])
                tail = re.search(r"\W*$", w["text"])
                overrides[w["key"]] = (
                    (lead.group(0) if lead else "")
                    + (o.right or "")
                    + (tail.group(0) if tail else "")
                    if o.right
                    else ""
                )
    return overrides


def apply(db: Session, er: EditRequest) -> Job | None:
    """Apply a planned edit. Returns the render job when the picture changes."""
    if er.status != EditStatus.planned:
        raise shorts_svc.ShortStateError(
            f"this edit is {er.status.value}, not waiting to be applied"
        )
    short = db.get(Short, er.short_id)
    if short is None or short.deleted_at is not None:
        raise shorts_svc.ShortStateError("the Short was deleted")
    ops = [EditOp.model_validate(o) for o in er.plan.get("ops", [])]
    patch: dict[str, Any] = {}
    opts: dict[str, Any] = {}
    trim = [o for o in ops if o.op == "trim"]
    for o in ops:
        if o.op == "set_hook":
            patch["hook"] = o.text
        elif o.op == "set_title":
            patch["title"] = o.text
        elif o.op == "set_keywords":
            patch["keywords"] = o.words
        elif o.op == "set_hashtags":
            patch["hashtags"] = o.words
        elif o.op == "set_style":
            opts["style"] = o.style
        elif o.op == "set_layout":
            opts["layout"] = o.layout
    if trim:
        view = shorts_svc.words_view(db, short, context_s=0)
        patch["start_s"] = view["start_s"] + sum(o.start_delta_s or 0 for o in trim)
        patch["end_s"] = view["end_s"] + sum(o.end_delta_s or 0 for o in trim)
    fixes = [o for o in ops if o.op == "fix_word"]
    if fixes:
        opts["caption_overrides"] = _fix_words(db, short, fixes)
    changed = shorts_svc.apply_patch(db, short, patch)
    job = None
    needs_render = bool(opts) or bool(changed & shorts_svc.PICTURE_FIELDS)
    if needs_render and short.active_version_id is not None:
        prev = db.get(ShortVersion, short.active_version_id)
        keep = (
            {k: v for k, v in (prev.settings or {}).items() if k in ("style", "layout", "aspects")}
            if prev
            else {}
        )
        job = versions.enqueue_render(
            db, short, {**keep, **opts, "origin": "ai_edit", "edit_id": str(er.id)}
        )
    er.status = EditStatus.applied
    db.commit()
    return job
