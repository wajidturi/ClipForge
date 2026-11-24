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
from clipforge.pipeline.render.scene import Captions, Scene


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
class RunRender(BaseModel):
    template: TemplateChoice = "auto"
    aspects: list[Literal["4:5", "1:1"]] = Field(default_factory=list)


class RunCreate(BaseModel):
    source_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    n: int = Field(default=5, ge=1, le=50, description="how many Shorts to pick")
    pick_mode: Literal["free", "smart", "deep", "whole"] = Field(
        default="smart", description="whole = each (short) source becomes one Short"
    )
    render: RunRender | None = Field(
        default=None, description="render the picks right away with this template"
    )
    topic: str | None = Field(default=None, max_length=200, description="e.g. a game or a name")
    ai_model: str | None = Field(default=None, max_length=100)
    length: Literal["short", "medium", "long"] = Field(
        default="short",
        description="short 15-60 s, medium 30-90 s, long = whole scenes up to 3 min",
    )


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
    reject_reason: str | None = None
    source_title: str | None = None
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


TemplateChoice = Literal[
    "auto", "streamer_first", "gameplay_first", "dual_vision", "floating_facecam", "cinematic"
]


class RenderRequest(BaseModel):
    template: TemplateChoice | None = Field(
        default=None, description="look of the Short; auto = by facecam detection"
    )
    scene: Scene | None = Field(
        default=None, description="the full look from the studio (overrides template/style)"
    )
    style: str | None = Field(default=None, description="caption preset id")
    layout: Literal["auto", "crop", "stack", "bubble", "full"] | None = Field(
        default=None, description="deprecated: use template"
    )
    aspects: list[Literal["4:5", "1:1"]] | None = None
    caption_overrides: dict[str, str] | None = Field(
        default=None,
        description="word key (source start time, 2 decimals) -> new text; empty hides the word."
        " Left out: the previous version's fixes are kept.",
    )
    origin: Literal["render", "rerender", "manual_edit"] | None = None

    @model_validator(mode="after")
    def _limit_overrides(self) -> RenderRequest:
        if self.caption_overrides and len(self.caption_overrides) > 2000:
            raise ValueError("too many caption fixes")
        if self.caption_overrides:
            self.caption_overrides = {k: v[:40] for k, v in self.caption_overrides.items()}
        return self


class RunRenderRequest(RenderRequest):
    short_ids: list[uuid.UUID] | None = Field(default=None, description="default: all picks")


class RenderQueued(BaseModel):
    job_ids: list[uuid.UUID]


class OptionOut(BaseModel):
    id: str
    label: str


class TemplateOut(BaseModel):
    id: str
    name: str
    tagline: str
    description: str
    needs_cam: bool
    controls: list[str]


class FontOut(BaseModel):
    id: str
    label: str
    category: str


class RenderOptions(BaseModel):
    styles: list[OptionOut]
    templates: list[TemplateOut]
    fonts: list[FontOut]
    caption_presets: dict[str, Captions]
    aspects: list[OptionOut]
    encoder: str


class CutOut(BaseModel):
    """What the studio's live preview needs about the prepared cut."""

    key: str
    preview_asset_id: uuid.UUID
    src_w: int
    src_h: int
    duration: float
    cam: list[float] | None
    targets: list[tuple[float, float | None]]
    cuts: list[float]
    zoom_peaks: list[float]
    words: list[tuple[float, float, str, str]] = Field(
        description="caption words: start, end (output s), text, key"
    )
    reaction: str | None


class StudioData(BaseModel):
    version_id: uuid.UUID | None
    scene: Scene
    note: str | None
    values: dict[str, str | None] = Field(description="placeholder values ({hook}, ...)")
    caption_overrides: dict[str, str]
    cut: CutOut | None = Field(description="null: render once to enable live editing")


class TemplateSwitch(BaseModel):
    template: TemplateChoice
    scene: Scene | None = Field(default=None, description="current scene (user layers are kept)")


class ImageOut(BaseModel):
    id: uuid.UUID
    name: str | None
    width: int | None
    height: int | None


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


# ------------------------------------------------------------------ Phase 6: settings
class SettingField(BaseModel):
    key: str
    section: str
    kind: Literal["bool", "int", "float", "str", "choice", "list"]
    nullable: bool
    choices: list[Any] | None
    min: float | None
    max: float | None
    value: Any
    default: Any = Field(description="value from the environment / built-in default")
    overridden: bool


class SettingsOut(BaseModel):
    fields: list[SettingField]


class SettingsPatch(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    reset: list[str] = Field(default_factory=list, description="keys to return to default")


# ------------------------------------------------------------------ library & review
class ShortPage(BaseModel):
    items: list[ShortOut]
    next_cursor: uuid.UUID | None
    total: int


class ReviewRequest(BaseModel):
    action: Literal["approve", "reject", "reopen"]
    reason: str | None = Field(default=None, max_length=500)


class BulkReviewRequest(ReviewRequest):
    short_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class BulkSkip(BaseModel):
    id: uuid.UUID
    reason: str


class BulkReviewOut(BaseModel):
    updated: list[uuid.UUID]
    skipped: list[BulkSkip]


class StatsOut(BaseModel):
    sources: dict[str, int]
    sources_ready: int
    shorts: dict[str, int]
    qc: dict[str, int]
    runs: int
    renders: int
    active_jobs: int


# ------------------------------------------------------------------ studio
class WordOut(BaseModel):
    key: str
    start: float
    end: float
    text: str
    override: str | None


class ContextSentence(BaseModel):
    start: float
    end: float
    text: str
    heat: float
    inside: bool


class ShortWords(BaseModel):
    start_s: float
    end_s: float
    words: list[WordOut]
    overrides: dict[str, str]
    sentences: list[ContextSentence]


class AIEditRequest(BaseModel):
    instruction: str = Field(min_length=2, max_length=2000)


class EditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    short_id: uuid.UUID
    kind: str
    instruction: str | None
    plan: dict[str, Any]
    status: str
    error: str | None
    base_version_id: uuid.UUID | None
    result_version_id: uuid.UUID | None
    created_at: datetime


class EditApplied(BaseModel):
    edit: EditOut
    short: ShortOut
    job_id: uuid.UUID | None
