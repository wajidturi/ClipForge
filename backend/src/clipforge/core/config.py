"""Application settings.

Layering: built-in defaults -> environment variables / `.env` (prefix ``CF_``)
-> values saved in the Settings page (database, see ``services/settings_store``).
Only a whitelisted set of fields can be changed from the UI; paths, ports and
secrets stay in the environment.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CF_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mode: Literal["local", "server"] = "local"
    data_dir: Path = Path("data")
    database_url: str = ""
    secret_key: SecretStr = SecretStr("change-me")
    host: str = "127.0.0.1"
    port: int = Field(default=8800, ge=1, le=65535)
    workers: int = Field(default=2, ge=0, le=64)
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"

    # Job queue tuning
    job_lease_seconds: int = Field(default=60, ge=5)
    job_poll_interval: float = Field(default=0.5, gt=0)
    event_poll_interval: float = Field(default=0.5, gt=0)

    # Ingestion (Phase 2)
    # Browser to borrow cookies from (e.g. "firefox") when a site asks for a sign-in/bot check
    ytdlp_cookies_browser: str | None = None
    ytdlp_retries: int = Field(default=5, ge=0, le=20)
    ytdlp_socket_timeout: float = Field(default=30, gt=0)
    max_source_hours: float = Field(default=4.0, gt=0)  # longer sources need a window
    default_window_hours: float = Field(default=2.0, gt=0)  # applied to over-long sources
    max_upload_mb: int = Field(default=20_000, gt=0)

    # Analysis (Phase 3)
    whisper_model: str | None = None  # None = small on GPU, base on CPU
    whisper_device: Literal["auto", "cuda", "cpu"] = "auto"
    transcribe_language: str | None = None  # None = detect
    ml_workers: int = Field(default=1, ge=0, le=8)  # workers allowed to run ML jobs
    vision_enabled: bool = True
    banner_ocr: bool = False
    banner_words: list[str] = Field(default_factory=list)  # empty = built-in list
    twitch_client_id: str | None = None
    twitch_client_secret: SecretStr | None = None
    chat_spike_ratio: float = Field(default=3.0, gt=1)
    chat_spike_min_per_min: float = Field(default=15.0, ge=0)
    loud_rise_db: float = Field(default=8.0, gt=0)

    # Moment selection (Phase 4)
    ai_provider: Literal["ollama", "none"] = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:4b"
    ai_timeout_s: float = Field(default=300, gt=0)
    candidates_k: int = Field(default=30, ge=5, le=120)

    # Rendering defaults (Phase 6; editable in Settings)
    render_style: str = "template"  # caption preset, or "template" = the template's own
    render_template: Literal[
        "auto", "streamer_first", "gameplay_first", "dual_vision", "floating_facecam", "cinematic"
    ] = "auto"
    render_aspects: list[Literal["4:5", "1:1"]] = Field(default_factory=list)
    auto_render: bool = False  # render picks as soon as a run finishes

    # First-run wizard finished (stored in the database by the UI)
    onboarded: bool = False

    # Where the built frontend lives (served by the API in production)
    frontend_dist: Path = Path(__file__).resolve().parents[4] / "frontend" / "dist"

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir.expanduser().resolve()

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.resolved_data_dir / 'clipforge.db').as_posix()}"

    @property
    def is_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
