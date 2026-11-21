"""Public API schemas (also the source of the generated TypeScript types)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clipforge.db.enums import (
    AssetKind,
    JobStatus,
    Platform,
    RunStatus,
    ShortStatus,
    SourceStatus,
)


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    mode: str


class GpuOut(BaseModel):
    name: str
    memory_total_mb: int
    driver: str


class SystemOut(BaseModel):
    os: str
    python: str
    cpu_cores: int
    ram_gb: float
    disk_free_gb: float
    gpus: list[GpuOut]
    ffmpeg: str | None
    ffprobe: str | None
    light_mode_recommended: bool
    data_dir: str
    database: Literal["sqlite", "postgresql"]


class CheckOut(BaseModel):
    name: str
    ok: bool
    detail: str
    fix: str | None
    required: bool


class DoctorOut(BaseModel):
    ok: bool
    checks: list[CheckOut]


class JobTypeOut(BaseModel):
    type: str
    caps: list[str]
    description: str


class JobCreate(BaseModel):
    type: str = Field(examples=["system.selftest"])
    payload: dict[str, Any] = Field(default_factory=dict)
    label: str | None = None
    priority: int = Field(default=100, ge=0, le=1000)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    run_id: uuid.UUID | None
    subject_type: str | None
    subject_id: uuid.UUID | None
    type: str
    label: str | None
    status: JobStatus
    progress: float
    step: str | None
    attempts: int
    max_attempts: int
    cancel_requested: bool
    error: str | None
    result: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobPage(BaseModel):
    items: list[JobOut]
    next_cursor: str | None


class JobEvent(BaseModel):
    type: Literal["job.updated"] = "job.updated"
    job: JobOut


# ------------------------------------------------------------------ sources
class SourceCreate(BaseModel):
    url: str = Field(
        min_length=4, max_length=2000, examples=["https://www.youtube.com/watch?v=..."]
    )
    start: str | None = Field(default=None, examples=["1:00:00"], description="window start")
    end: str | None = Field(default=None, examples=["1:30:00"], description="window end")


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: AssetKind
    bytes: int | None
    duration_s: float | None
    width: int | None
    height: int | None
    codec: str | None
    created_at: datetime


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: Platform
    external_id: str
    url: str
    title: str | None
    channel_name: str | None
    duration_s: float | None
    published_at: datetime | None
    language: str | None
    window_start_s: float | None
    window_end_s: float | None
    status: SourceStatus
    skip_reason: str | None
    error: str | None
    error_hint: str | None
    latest_job_id: uuid.UUID | None
    thumbnail: str | None = None
    window_note: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _from_meta(cls, v: Any) -> Any:
        meta = getattr(v, "meta", None)
        if isinstance(meta, dict):
            data = {k: getattr(v, k) for k in cls.model_fields if hasattr(v, k)}
            data["thumbnail"] = meta.get("thumbnail")
            data["window_note"] = meta.get("window_note")
            return data
        return v


class SourceDetail(SourceOut):
    assets: list[AssetOut] = Field(default_factory=list)
    chapters: list[dict[str, Any]] = Field(default_factory=list)
    has_heatmap: bool = False


class SourceCreated(BaseModel):
    source: SourceOut
    created: bool
    job_id: uuid.UUID | None


class SourcePage(BaseModel):
    items: list[SourceOut]
    next_cursor: str | None


class SourceEvent(BaseModel):
    type: Literal["source.updated"] = "source.updated"
    source: SourceOut


class SourceDeleted(BaseModel):
    type: Literal["source.deleted"] = "source.deleted"
    id: uuid.UUID


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    idx: int
    start_s: float
    end_s: float
    text: str
    heat: float
    tags: list[dict[str, Any]]


class TranscriptOut(BaseModel):
    language: str | None
    language_prob: float | None
    model: str
    device: str
    word_count: int
    segments: list[SegmentOut]


class Marker(BaseModel):
    type: str
    start_s: float
    end_s: float
    score: float
    label: str | None


class TimelineOut(BaseModel):
    """Everything the timeline graph needs, already downsampled to `bins` points."""

    start_s: float
    end_s: float
    bins: int
    heat: list[float]  # 0..100, max heat of sentences in each bin
    loud: list[float]  # 0..1
    chat: list[float]  # 0..1 (relative to the busiest bin)
    motion: list[float]  # 0..1
    replay: list[float]  # 0..1
    markers: list[Marker]
    available: list[str]
    steps: dict[str, str]
    warnings: list[str]


class AnalyzeRequest(BaseModel):
    vision: bool | None = Field(default=None, description="analyse the picture (default: setting)")
    banners: bool | None = Field(default=None, description="read on-screen banners (slow)")
    force_transcribe: bool = False


# ------------------------------------------------------------------ runs & picks
class RunCreate(BaseModel):
    source_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    n: int = Field(default=5, ge=1, le=20, description="how many Shorts to pick")
    pick_mode: Literal["free", "smart", "deep"] = "smart"
    topic: str | None = Field(default=None, max_length=200, description="e.g. a game or a name")
    ai_model: str | None = Field(default=None, max_length=100)


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: RunStatus
    params: dict[str, Any]
    ai_provider: str | None
    ai_model: str | None
    ai_usage: dict[str, Any]
    result: dict[str, Any]
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ShortPartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    idx: int
    start_s: float
    end_s: float
    label: str | None


class ActiveVersion(BaseModel):
    id: uuid.UUID
    version_no: int
    origin: str
    layout: str | None
    style: str | None
    mp4_asset_id: uuid.UUID | None
    cover_asset_id: uuid.UUID | None
    extra_assets: dict[str, uuid.UUID] = Field(default_factory=dict)
    qc_verdict: str | None
    qc_reasons: list[str] = Field(default_factory=list)
    render_ms: int | None
    duration_s: float | None


class ShortOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID | None
    source_id: uuid.UUID
    format: str
    hook: str | None
    title: str | None
    hashtags: list[str]
    keywords: list[str]
    credit: str | None
    score: float | None
    ai_reason: str | None
    status: ShortStatus
    parts: list[ShortPartOut] = Field(default_factory=list)
    has_preview: bool = False
    active: ActiveVersion | None = None
    render_job_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class VersionOut(ActiveVersion):
    created_at: datetime
    qc_checks: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)


class ShortDetail(ShortOut):
    versions: list[VersionOut] = Field(default_factory=list)


class RenderRequest(BaseModel):
    style: str | None = Field(default=None, description="caption style id")
    layout: Literal["auto", "crop", "stack", "bubble", "full"] | None = None
    aspects: list[Literal["4:5", "1:1"]] | None = None


class RunRenderRequest(RenderRequest):
    short_ids: list[uuid.UUID] | None = Field(default=None, description="default: all picks")


class RenderQueued(BaseModel):
    job_ids: list[uuid.UUID]


class OptionOut(BaseModel):
    id: str
    label: str


class RenderOptions(BaseModel):
    styles: list[OptionOut]
    layouts: list[OptionOut]
    aspects: list[OptionOut]
    encoder: str


class ShortEvent(BaseModel):
    type: Literal["short.updated"] = "short.updated"
    id: uuid.UUID
    run_id: uuid.UUID | None
    status: ShortStatus


class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank: int
    source_id: uuid.UUID
    start_s: float
    end_s: float
    score: float
    tags: list[str]
    head_text: str | None
    tail_text: str | None


class RunDetail(RunOut):
    shorts: list[ShortOut]
    candidates: list[CandidateOut]
    job_id: uuid.UUID | None


class RunEvent(BaseModel):
    type: Literal["run.updated"] = "run.updated"
    run: RunOut


class ShortPatch(BaseModel):
    hook: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=200)
    hashtags: list[str] | None = None
    keywords: list[str] | None = None
    start_s: float | None = Field(default=None, ge=0)
    end_s: float | None = Field(default=None, ge=0)


class AIStatusOut(BaseModel):
    provider: str
    model: str | None
    ok: bool
    detail: str
    models: list[str]


class PlatformOut(BaseModel):
    id: Platform
    name: str
    example: str
