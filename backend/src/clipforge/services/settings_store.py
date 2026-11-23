"""Settings saved from the UI, layered over the environment.

Why: a creator should be able to switch the AI model, caption style or Whisper
model from the Settings page without editing `.env` and restarting. Only the
fields in ``EDITABLE`` can be changed this way (paths, ports and secrets stay in
the environment). Each saved value is one row in the ``settings`` table
(``{"v": value}``) and is validated with the same pydantic rules as ``Settings``.

``effective()`` is what services call instead of ``get_settings()`` for these
fields. The API and the worker processes each keep a 5-second cache, so a change
made in the UI reaches the workers within a few seconds without any messaging.
"""

from __future__ import annotations

import threading
import time
import types
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Union, get_args, get_origin

import annotated_types as at
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from clipforge.core.config import Settings, get_settings
from clipforge.core.logging import get_logger
from clipforge.db.models import Setting
from clipforge.db.session import get_sessionmaker

log = get_logger(__name__)

# key -> section shown in the UI (order = display order)
EDITABLE: dict[str, str] = {
    "ai_provider": "ai",
    "ollama_url": "ai",
    "ollama_model": "ai",
    "ai_timeout_s": "ai",
    "candidates_k": "ai",
    "whisper_model": "analysis",
    "whisper_device": "analysis",
    "transcribe_language": "analysis",
    "vision_enabled": "analysis",
    "banner_ocr": "analysis",
    "loud_rise_db": "analysis",
    "chat_spike_ratio": "analysis",
    "chat_spike_min_per_min": "analysis",
    "render_style": "render",
    "render_layout": "render",
    "render_aspects": "render",
    "auto_render": "render",
    "ytdlp_cookies_browser": "sources",
    "max_source_hours": "sources",
    "default_window_hours": "sources",
    "onboarded": "app",
}

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]
BROWSERS = ["chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium"]
CACHE_S = 5.0


def _extra_choices(key: str) -> list[Any] | None:
    if key == "render_style":
        from clipforge.pipeline.render.captions import STYLES

        return list(STYLES)
    if key == "whisper_model":
        return WHISPER_MODELS
    if key == "ytdlp_cookies_browser":
        return BROWSERS
    return None


class SettingsError(ValueError):
    def __init__(self, key: str, message: str) -> None:
        super().__init__(f"{key}: {message}")
        self.key = key
        self.message = message


# ------------------------------------------------------------------ field description
def _unwrap_optional(ann: Any) -> tuple[Any, bool]:
    if get_origin(ann) in (Union, types.UnionType):
        args = [a for a in get_args(ann) if a is not type(None)]
        if len(args) == 1 and len(get_args(ann)) == 2:
            return args[0], True
    return ann, False


def describe(key: str) -> dict[str, Any]:
    """Kind, choices and bounds of one editable field (drives the Settings form)."""
    f = Settings.model_fields[key]
    ann, nullable = _unwrap_optional(f.annotation)
    choices: list[Any] | None = None
    if get_origin(ann) is Literal:
        kind, choices = "choice", list(get_args(ann))
    elif get_origin(ann) is list:
        inner = get_args(ann)[0] if get_args(ann) else str
        kind = "list"
        if get_origin(inner) is Literal:
            choices = list(get_args(inner))
    elif ann is bool:
        kind = "bool"
    elif ann is int:
        kind = "int"
    elif ann is float:
        kind = "float"
    else:
        kind = "str"
    if choices is None and (extra := _extra_choices(key)) is not None:
        choices = extra
        kind = "choice" if kind == "str" else kind
    lo = hi = None
    for m in f.metadata:
        if isinstance(m, at.Ge | at.Gt):
            lo = m.ge if isinstance(m, at.Ge) else m.gt
        elif isinstance(m, at.Le | at.Lt):
            hi = m.le if isinstance(m, at.Le) else m.lt
    return {
        "key": key,
        "section": EDITABLE[key],
        "kind": kind,
        "nullable": nullable,
        "choices": choices,
        "min": lo,
        "max": hi,
    }


def _adapter(key: str) -> TypeAdapter[Any]:
    f = Settings.model_fields[key]
    ann: Any = Annotated[f.annotation, *f.metadata] if f.metadata else f.annotation
    return TypeAdapter(ann)


def validate(key: str, value: Any) -> Any:
    if key not in EDITABLE:
        raise SettingsError(key, "this setting cannot be changed from the app")
    try:
        v = _adapter(key).validate_python(value)
    except ValidationError as e:
        raise SettingsError(key, e.errors()[0]["msg"]) from None
    d = describe(key)
    if isinstance(v, str):
        v = v.strip()
        if v == "" and d["nullable"]:
            v = None
    if key == "render_style" and v not in (d["choices"] or []):
        raise SettingsError(key, f"unknown caption style '{v}'")
    if isinstance(v, list):
        v = list(dict.fromkeys(v))  # de-duplicate, keep order
    return v


# ------------------------------------------------------------------ read
_lock = threading.Lock()
_cache: tuple[int, float, Settings, dict[str, Any]] | None = None


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def _load_overrides(db: Session) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for row in db.scalars(select(Setting).where(Setting.key.in_(EDITABLE))):
        raw = (row.value or {}).get("v")
        try:
            out[row.key] = validate(row.key, raw)
        except SettingsError as e:  # e.g. a choice that no longer exists: ignore it
            log.warning("settings.ignored", key=row.key, reason=e.message)
    return out


def _compute(db: Session | None) -> tuple[Settings, dict[str, Any]]:
    base = get_settings()
    try:
        if db is not None:
            overrides = _load_overrides(db)
        else:
            with get_sessionmaker()() as s:
                overrides = _load_overrides(s)
    except SQLAlchemyError:  # no table yet (before migrations) -> environment only
        overrides = {}
    return base.model_copy(update=overrides), overrides


def _cached(db: Session | None) -> tuple[Settings, dict[str, Any]]:
    global _cache
    base_id = id(get_settings())
    now = time.monotonic()
    with _lock:
        c = _cache
    if c and c[0] == base_id and now - c[1] < CACHE_S:
        return c[2], c[3]
    eff, overrides = _compute(db)
    with _lock:
        _cache = (base_id, now, eff, overrides)
    return eff, overrides


def effective(db: Session | None = None) -> Settings:
    """Environment settings with the values saved in the app applied on top."""
    return _cached(db)[0]


def overrides(db: Session | None = None) -> dict[str, Any]:
    return dict(_cached(db)[1])


def fields(db: Session) -> list[dict[str, Any]]:
    invalidate()
    eff, saved = _cached(db)
    base = get_settings()
    return [
        {
            **describe(k),
            "value": getattr(eff, k),
            "default": getattr(base, k),
            "overridden": k in saved,
        }
        for k in EDITABLE
    ]


# ------------------------------------------------------------------ write
def save(db: Session, values: dict[str, Any], reset: list[str] | None = None) -> None:
    """Validate everything first, then write; nothing is saved if one value is invalid."""
    clean = {k: validate(k, v) for k, v in values.items()}
    for k in reset or []:
        if k not in EDITABLE:
            raise SettingsError(k, "this setting cannot be changed from the app")
    now = datetime.now(UTC)
    for k in reset or []:
        row = db.get(Setting, k)
        if row is not None:
            db.delete(row)
    for k, v in clean.items():
        row = db.get(Setting, k)
        if row is None:
            db.add(Setting(key=k, value={"v": v}, updated_at=now))
        else:
            row.value = {"v": v}
            row.updated_at = now
    db.commit()
    invalidate()
    log.info("settings.saved", keys=sorted(clean), reset=sorted(reset or []))
