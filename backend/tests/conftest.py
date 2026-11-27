from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from clipforge.core.config import get_settings
from clipforge.db import migrate
from clipforge.db.session import get_engine, get_sessionmaker
from clipforge.pipeline.transcription.sentences import Word
from clipforge.pipeline.transcription.whisper import TranscribeResult
from clipforge.services import settings_store


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    settings_store.invalidate()


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Every test gets its own data dir and SQLite database."""
    data = tmp_path / "data"
    monkeypatch.setenv("CF_DATA_DIR", str(data))
    monkeypatch.setenv("CF_DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("CF_EVENT_POLL_INTERVAL", "0.05")
    monkeypatch.setenv("CF_JOB_POLL_INTERVAL", "0.05")
    monkeypatch.setenv("CF_FRONTEND_DIST", str(tmp_path / "no-frontend"))
    # Fast, offline defaults; tests that need the picture analysis turn it on.
    monkeypatch.setenv("CF_VISION_ENABLED", "false")
    _clear_caches()
    yield data
    get_engine().dispose()
    _clear_caches()


# Words the fake speech model "hears" (audio-relative seconds).
FAKE_WORDS = [
    Word(0.5, 0.9, " The", 0.99),
    Word(0.9, 1.3, " car", 0.99),
    Word(1.3, 1.9, " crashed.", 0.99),
    Word(3.0, 3.4, " Ha", 0.9),
    Word(3.4, 3.8, " ha", 0.9),
    Word(3.8, 4.2, " ha!", 0.9),
    Word(6.0, 6.5, " No", 0.99),
    Word(6.5, 7.0, " way.", 0.99),
]


class FakeTranscriber:
    calls = 0

    def transcribe(self, audio: Path, **kw: Any) -> TranscribeResult:
        FakeTranscriber.calls += 1
        if kw.get("progress"):
            kw["progress"](50.0, "transcribing")
        return TranscribeResult(list(FAKE_WORDS), "en", 0.99, "fake", "cpu", 10.0)


@pytest.fixture(autouse=True)
def fake_speech_model(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace Whisper with a fixed transcript unless a test is marked `real_ml`."""
    if request.node.get_closest_marker("real_ml"):
        return
    FakeTranscriber.calls = 0
    monkeypatch.setattr(
        "clipforge.services.analyze.make_transcriber", lambda settings: FakeTranscriber()
    )


@pytest.fixture
def migrated() -> None:
    migrate.upgrade(get_settings().resolved_database_url)


@pytest.fixture
def db(migrated: None) -> Iterator[Session]:
    with get_sessionmaker()() as s:
        yield s


@pytest.fixture(autouse=True)
def offline_cutout_model(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """No 16 MB model downloads in tests: renders use the original facecam unless a test
    provides a segmenter (or is marked `real_ml`)."""
    if request.node.get_closest_marker("real_ml"):
        return

    def offline(_d: Path) -> Path:
        raise OSError("offline in tests")

    monkeypatch.setattr("clipforge.pipeline.signals.vision.ensure_segment_model", offline)
