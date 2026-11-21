"""Status / kind enums. Stored as VARCHAR (non-native) so both engines behave the same."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum


def enum_type(cls: type[StrEnum]) -> Enum:
    return Enum(
        cls,
        native_enum=False,
        create_constraint=False,
        validate_strings=True,
        length=24,
        values_callable=lambda e: [m.value for m in e],
    )


class Mode(StrEnum):
    local = "local"
    server = "server"


class UserRole(StrEnum):
    owner = "owner"
    editor = "editor"
    viewer = "viewer"


class Platform(StrEnum):
    youtube = "youtube"
    twitch = "twitch"
    kick = "kick"
    tiktok = "tiktok"
    x = "x"
    instagram = "instagram"
    facebook = "facebook"
    rumble = "rumble"
    vimeo = "vimeo"
    reddit = "reddit"
    dailymotion = "dailymotion"
    file = "file"
    other = "other"


class ClipPolicy(StrEnum):
    allowed = "allowed"
    ask = "ask"
    denied = "denied"
    unknown = "unknown"


class DiscoveryKind(StrEnum):
    rss = "rss"
    search = "search"
    category = "category"


class SourceStatus(StrEnum):
    new = "new"
    downloading = "downloading"
    analyzing = "analyzing"
    ready = "ready"
    failed = "failed"
    skipped = "skipped"


class AssetOwner(StrEnum):
    source = "source"
    short_version = "short_version"
    live_session = "live_session"
    run = "run"


class AssetKind(StrEnum):
    audio = "audio"
    video = "video"
    segment = "segment"
    proxy = "proxy"
    mp4 = "mp4"
    cover = "cover"
    aspect_4x5 = "aspect_4x5"
    aspect_1x1 = "aspect_1x1"
    caption_ass = "caption_ass"
    peek = "peek"
    sheet = "sheet"
    voice = "voice"
    words = "words"


class Storage(StrEnum):
    local = "local"
    s3 = "s3"


class SignalType(StrEnum):
    loud = "loud"
    chat_rate = "chat_rate"
    chat_spike = "chat_spike"
    clip = "clip"
    replay = "replay"
    moment = "moment"
    banner = "banner"
    cut = "cut"
    laugh = "laugh"


class RunTrigger(StrEnum):
    manual = "manual"
    autopilot = "autopilot"
    live = "live"


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class ShortFormat(StrEnum):
    moment = "moment"
    callback = "callback"
    compilation = "compilation"
    escalation = "escalation"
    thenvsnow = "thenvsnow"
    reveal = "reveal"
    chat = "chat"
    waitforit = "waitforit"


class ShortStatus(StrEnum):
    picked = "picked"
    rendering = "rendering"
    review = "review"
    approved = "approved"
    rejected = "rejected"
    scheduled = "scheduled"
    published = "published"
    failed = "failed"
    dropped = "dropped"


class VersionOrigin(StrEnum):
    render = "render"
    rerender = "rerender"
    manual_edit = "manual_edit"
    ai_edit = "ai_edit"
    voice = "voice"
    recut = "recut"


class VersionStatus(StrEnum):
    pending = "pending"
    rendering = "rendering"
    ready = "ready"
    failed = "failed"


class QcVerdict(StrEnum):
    pass_ = "pass"  # noqa: S105 - QC verdict, not a password
    warn = "warn"
    fail = "fail"


class EditKind(StrEnum):
    ai = "ai"
    manual = "manual"


class EditStatus(StrEnum):
    pending = "pending"
    planned = "planned"
    applied = "applied"
    failed = "failed"


class ScheduleStatus(StrEnum):
    planned = "planned"
    approved = "approved"
    sending = "sending"
    sent = "sent"
    failed = "failed"
    cancelled = "cancelled"


class IntegrationStatus(StrEnum):
    unknown = "unknown"
    ok = "ok"
    error = "error"


class LiveStatus(StrEnum):
    waiting = "waiting"
    recording = "recording"
    stopped = "stopped"
    failed = "failed"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"

    @property
    def is_final(self) -> bool:
        return self in (JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled)
