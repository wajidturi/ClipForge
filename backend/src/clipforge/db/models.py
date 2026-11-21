"""ORM models: the full schema from docs/05-database-design.md.

Phase 1 creates every table so later phases only add behaviour, not structure.
Large data (word timings, frames, media) lives on disk; rows hold paths and hashes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from clipforge.db.base import Base, IdMixin, TimestampMixin
from clipforge.db.enums import (
    AssetKind,
    AssetOwner,
    ClipPolicy,
    DiscoveryKind,
    EditKind,
    EditStatus,
    IntegrationStatus,
    JobStatus,
    LiveStatus,
    Platform,
    QcVerdict,
    RunStatus,
    RunTrigger,
    ScheduleStatus,
    ShortFormat,
    ShortStatus,
    SignalType,
    SourceStatus,
    Storage,
    UserRole,
    VersionOrigin,
    VersionStatus,
    enum_type,
)


def fk(target: str, *, nullable: bool = False, ondelete: str = "CASCADE") -> Any:
    return mapped_column(ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True)


# --------------------------------------------------------------------- identity & settings
class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(enum_type(UserRole), default=UserRole.owner)
    locale: Mapped[str] = mapped_column(String(16), default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_by: Mapped[uuid.UUID | None] = fk("users.id", nullable=True, ondelete="SET NULL")
    updated_at: Mapped[datetime | None]


class Integration(IdMixin, TimestampMixin, Base):
    __tablename__ = "integrations"
    provider: Mapped[str] = mapped_column(String(40), index=True)
    label: Mapped[str] = mapped_column(String(120))
    secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[IntegrationStatus] = mapped_column(
        enum_type(IntegrationStatus), default=IntegrationStatus.unknown
    )
    last_tested_at: Mapped[datetime | None]


class Theme(IdMixin, TimestampMixin, Base):
    __tablename__ = "themes"
    name: Mapped[str] = mapped_column(String(80), unique=True)
    palette: Mapped[dict[str, Any]] = mapped_column(default=dict)
    font: Mapped[str | None] = mapped_column(String(120))
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class BrandProfile(IdMixin, TimestampMixin, Base):
    __tablename__ = "brand_profiles"
    name: Mapped[str] = mapped_column(String(80))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    watermark: Mapped[dict[str, Any]] = mapped_column(default=dict)
    progress_bar: Mapped[bool] = mapped_column(Boolean, default=False)
    endcard_text: Mapped[str | None] = mapped_column(String(120))
    theme_id: Mapped[uuid.UUID | None] = fk("themes.id", nullable=True, ondelete="SET NULL")
    default_style: Mapped[str | None] = mapped_column(String(40))
    default_layout: Mapped[str | None] = mapped_column(String(40))
    music_default: Mapped[str | None] = mapped_column(String(80))
    fonts: Mapped[dict[str, Any]] = mapped_column(default=dict)


# --------------------------------------------------------------------- creators & sources
class Creator(IdMixin, TimestampMixin, Base):
    __tablename__ = "creators"
    __table_args__ = (UniqueConstraint("platform", "handle", name="uq_creators_platform_handle"),)
    platform: Mapped[Platform] = mapped_column(enum_type(Platform))
    handle: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str | None] = mapped_column(String(200))
    language: Mapped[str | None] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    clip_policy: Mapped[ClipPolicy] = mapped_column(
        enum_type(ClipPolicy), default=ClipPolicy.unknown
    )
    policy_note: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(String(1000))


class DiscoveryRule(IdMixin, TimestampMixin, Base):
    __tablename__ = "discovery_rules"
    kind: Mapped[DiscoveryKind] = mapped_column(enum_type(DiscoveryKind))
    query: Mapped[str] = mapped_column(String(500))
    keyword_regex: Mapped[str | None] = mapped_column(String(500))
    language: Mapped[str | None] = mapped_column(String(16))
    max_duration_s: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Source(IdMixin, TimestampMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_sources_platform_external_id"),
    )
    creator_id: Mapped[uuid.UUID | None] = fk("creators.id", nullable=True, ondelete="SET NULL")
    platform: Mapped[Platform] = mapped_column(enum_type(Platform))
    external_id: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str | None] = mapped_column(String(500))
    channel_name: Mapped[str | None] = mapped_column(String(200))
    duration_s: Mapped[float | None] = mapped_column(Float)
    published_at: Mapped[datetime | None]
    language: Mapped[str | None] = mapped_column(String(16))
    window_start_s: Mapped[float | None] = mapped_column(Float)
    window_end_s: Mapped[float | None] = mapped_column(Float)
    status: Mapped[SourceStatus] = mapped_column(enum_type(SourceStatus), default=SourceStatus.new)
    skip_reason: Mapped[str | None] = mapped_column(String(300))
    error: Mapped[str | None] = mapped_column(Text)
    error_hint: Mapped[str | None] = mapped_column(String(500))
    # Plain column: the job that is (or last was) ingesting this source.
    latest_job_id: Mapped[uuid.UUID | None]
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)


class MediaAsset(IdMixin, TimestampMixin, Base):
    __tablename__ = "media_assets"
    __table_args__ = (Index("ix_media_assets_owner", "owner_type", "owner_id"),)
    owner_type: Mapped[AssetOwner] = mapped_column(enum_type(AssetOwner))
    owner_id: Mapped[uuid.UUID]
    kind: Mapped[AssetKind] = mapped_column(enum_type(AssetKind))
    storage: Mapped[Storage] = mapped_column(enum_type(Storage), default=Storage.local)
    path: Mapped[str] = mapped_column(String(1000))
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    duration_s: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    codec: Mapped[str | None] = mapped_column(String(40))


# --------------------------------------------------------------------- analysis
class Transcript(IdMixin, TimestampMixin, Base):
    __tablename__ = "transcripts"
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), unique=True
    )
    model: Mapped[str] = mapped_column(String(60))
    device: Mapped[str] = mapped_column(String(20))
    language: Mapped[str | None] = mapped_column(String(16))
    language_prob: Mapped[float | None] = mapped_column(Float)
    words_path: Mapped[str] = mapped_column(String(1000))
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    processing_s: Mapped[float | None] = mapped_column(Float)


class Segment(IdMixin, Base):
    __tablename__ = "segments"
    __table_args__ = (Index("ix_segments_transcript_start", "transcript_id", "start_s"),)
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE")
    )
    idx: Mapped[int] = mapped_column(Integer)
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    heat: Mapped[float] = mapped_column(Float, default=0.0)
    tags: Mapped[list[Any]] = mapped_column(default=list)


class Signal(IdMixin, TimestampMixin, Base):
    __tablename__ = "signals"
    __table_args__ = (Index("ix_signals_source_type_start", "source_id", "type", "start_s"),)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    type: Mapped[SignalType] = mapped_column(enum_type(SignalType))
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    label: Mapped[str | None] = mapped_column(String(120))
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)


class UsedRange(IdMixin, TimestampMixin, Base):
    __tablename__ = "used_ranges"
    source_id: Mapped[uuid.UUID] = fk("sources.id")
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    short_id: Mapped[uuid.UUID | None] = fk("shorts.id", nullable=True, ondelete="SET NULL")


# --------------------------------------------------------------------- runs, selection, shorts
class Run(IdMixin, TimestampMixin, Base):
    __tablename__ = "runs"
    user_id: Mapped[uuid.UUID | None] = fk("users.id", nullable=True, ondelete="SET NULL")
    trigger: Mapped[RunTrigger] = mapped_column(enum_type(RunTrigger), default=RunTrigger.manual)
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[RunStatus] = mapped_column(enum_type(RunStatus), default=RunStatus.queued)
    ai_provider: Mapped[str | None] = mapped_column(String(40))
    ai_model: Mapped[str | None] = mapped_column(String(80))
    ai_usage: Mapped[dict[str, Any]] = mapped_column(default=dict)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)


class RunSource(Base):
    __tablename__ = "run_sources"
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )


class Candidate(IdMixin, TimestampMixin, Base):
    __tablename__ = "candidates"
    run_id: Mapped[uuid.UUID] = fk("runs.id")
    source_id: Mapped[uuid.UUID] = fk("sources.id")
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)
    tags: Mapped[list[Any]] = mapped_column(default=list)
    head_text: Mapped[str | None] = mapped_column(Text)
    tail_text: Mapped[str | None] = mapped_column(Text)
    rank: Mapped[int] = mapped_column(Integer)


class Short(IdMixin, TimestampMixin, Base):
    __tablename__ = "shorts"
    run_id: Mapped[uuid.UUID | None] = fk("runs.id", nullable=True, ondelete="SET NULL")
    source_id: Mapped[uuid.UUID] = fk("sources.id")
    format: Mapped[ShortFormat] = mapped_column(enum_type(ShortFormat), default=ShortFormat.moment)
    hook: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str | None] = mapped_column(String(200))
    hashtags: Mapped[list[Any]] = mapped_column(default=list)
    keywords: Mapped[list[Any]] = mapped_column(default=list)
    credit: Mapped[str | None] = mapped_column(String(200))
    score: Mapped[float | None] = mapped_column(Float)
    ai_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ShortStatus] = mapped_column(
        enum_type(ShortStatus), default=ShortStatus.picked, index=True
    )
    reject_reason: Mapped[str | None] = mapped_column(String(500))
    # Plain column (no FK) to avoid a circular dependency with short_versions.
    active_version_id: Mapped[uuid.UUID | None]
    deleted_at: Mapped[datetime | None]


class ShortPart(IdMixin, Base):
    __tablename__ = "short_parts"
    short_id: Mapped[uuid.UUID] = fk("shorts.id")
    idx: Mapped[int] = mapped_column(Integer)
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    label: Mapped[str | None] = mapped_column(String(80))


class ShortVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "short_versions"
    __table_args__ = (UniqueConstraint("short_id", "version_no", name="uq_short_versions_no"),)
    short_id: Mapped[uuid.UUID] = fk("shorts.id")
    version_no: Mapped[int] = mapped_column(Integer)
    origin: Mapped[VersionOrigin] = mapped_column(enum_type(VersionOrigin))
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    edl: Mapped[list[Any]] = mapped_column(default=list)
    caption_overrides: Mapped[dict[str, Any]] = mapped_column(default=dict)
    crop_plan_path: Mapped[str | None] = mapped_column(String(1000))
    render_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[VersionStatus] = mapped_column(
        enum_type(VersionStatus), default=VersionStatus.pending
    )


class QcReport(IdMixin, TimestampMixin, Base):
    __tablename__ = "qc_reports"
    short_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("short_versions.id", ondelete="CASCADE"), unique=True
    )
    verdict: Mapped[QcVerdict] = mapped_column(enum_type(QcVerdict))
    checks: Mapped[dict[str, Any]] = mapped_column(default=dict)
    reasons: Mapped[list[Any]] = mapped_column(default=list)


class EditRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "edit_requests"
    short_id: Mapped[uuid.UUID] = fk("shorts.id")
    base_version_id: Mapped[uuid.UUID | None] = fk(
        "short_versions.id", nullable=True, ondelete="SET NULL"
    )
    kind: Mapped[EditKind] = mapped_column(enum_type(EditKind))
    instruction: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result_version_id: Mapped[uuid.UUID | None] = fk(
        "short_versions.id", nullable=True, ondelete="SET NULL"
    )
    status: Mapped[EditStatus] = mapped_column(enum_type(EditStatus), default=EditStatus.pending)
    error: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------- scheduling & publishing
class ScheduleEntry(IdMixin, TimestampMixin, Base):
    __tablename__ = "schedule_entries"
    short_version_id: Mapped[uuid.UUID] = fk("short_versions.id")
    integration_id: Mapped[uuid.UUID | None] = fk(
        "integrations.id", nullable=True, ondelete="SET NULL"
    )
    platform: Mapped[Platform] = mapped_column(enum_type(Platform))
    scheduled_at_utc: Mapped[datetime] = mapped_column(index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    caption_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ScheduleStatus] = mapped_column(
        enum_type(ScheduleStatus), default=ScheduleStatus.planned
    )
    external_post_id: Mapped[str | None] = mapped_column(String(200))
    external_url: Mapped[str | None] = mapped_column(String(1000))
    error: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[uuid.UUID | None] = fk("users.id", nullable=True, ondelete="SET NULL")
    confirmed_at: Mapped[datetime | None]


class AutopilotConfig(IdMixin, TimestampMixin, Base):
    __tablename__ = "autopilot_configs"
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    days: Mapped[list[Any]] = mapped_column(default=list)
    time_local: Mapped[str] = mapped_column(String(5), default="09:00")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    last_run_id: Mapped[uuid.UUID | None] = fk("runs.id", nullable=True, ondelete="SET NULL")
    next_run_at: Mapped[datetime | None]


# --------------------------------------------------------------------- live
class LiveSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "live_sessions"
    creator_id: Mapped[uuid.UUID | None] = fk("creators.id", nullable=True, ondelete="SET NULL")
    url: Mapped[str] = mapped_column(String(2000))
    platform: Mapped[Platform] = mapped_column(enum_type(Platform))
    status: Mapped[LiveStatus] = mapped_column(enum_type(LiveStatus), default=LiveStatus.waiting)
    started_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
    buffer_dir: Mapped[str | None] = mapped_column(String(1000))
    ratio: Mapped[float] = mapped_column(Float, default=3.0)
    min_rate: Mapped[int] = mapped_column(Integer, default=15)
    baseline_rate: Mapped[float | None] = mapped_column(Float)


class ChatSpike(IdMixin, TimestampMixin, Base):
    __tablename__ = "chat_spikes"
    live_session_id: Mapped[uuid.UUID] = fk("live_sessions.id")
    t_utc: Mapped[datetime]
    rate: Mapped[float] = mapped_column(Float)
    ratio: Mapped[float] = mapped_column(Float)
    top_lines: Mapped[list[Any]] = mapped_column(default=list)
    clip_asset_id: Mapped[uuid.UUID | None] = fk(
        "media_assets.id", nullable=True, ondelete="SET NULL"
    )
    candidate_id: Mapped[uuid.UUID | None] = fk("candidates.id", nullable=True, ondelete="SET NULL")


# --------------------------------------------------------------------- insights
class ChannelInsight(IdMixin, TimestampMixin, Base):
    __tablename__ = "channel_insights"
    channel_handle: Mapped[str] = mapped_column(String(200), index=True)
    fetched_at: Mapped[datetime]
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict)
    learned_rules: Mapped[list[Any]] = mapped_column(default=list)


class PostMetric(IdMixin, TimestampMixin, Base):
    __tablename__ = "post_metrics"
    schedule_entry_id: Mapped[uuid.UUID] = fk("schedule_entries.id")
    views: Mapped[int | None] = mapped_column(BigInteger)
    avg_view_pct: Mapped[float | None] = mapped_column(Float)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    fetched_at: Mapped[datetime]


# --------------------------------------------------------------------- jobs & audit
class Job(IdMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_queue", "status", "priority", "created_at"),
        Index("ix_jobs_subject", "subject_type", "subject_id"),
    )
    parent_id: Mapped[uuid.UUID | None] = fk("jobs.id", nullable=True, ondelete="SET NULL")
    run_id: Mapped[uuid.UUID | None] = fk("runs.id", nullable=True, ondelete="SET NULL")
    # What the job works on, e.g. ("source", <id>). Generic, so no FK.
    subject_type: Mapped[str | None] = mapped_column(String(32))
    subject_id: Mapped[uuid.UUID | None]
    type: Mapped[str] = mapped_column(String(60), index=True)
    label: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    required_caps: Mapped[list[Any]] = mapped_column(default=list)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[JobStatus] = mapped_column(enum_type(JobStatus), default=JobStatus.queued)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime | None]
    lease_owner: Mapped[str | None] = mapped_column(String(120))
    lease_until: Mapped[datetime | None]
    heartbeat_at: Mapped[datetime | None]
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    step: Mapped[str | None] = mapped_column(String(200))
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    log_path: Mapped[str | None] = mapped_column(String(1000))
    cache_key: Mapped[str | None] = mapped_column(String(128), index=True)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_log"
    user_id: Mapped[uuid.UUID | None] = fk("users.id", nullable=True, ondelete="SET NULL")
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    at: Mapped[datetime] = mapped_column(index=True)
