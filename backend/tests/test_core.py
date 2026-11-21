from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clipforge.core import system
from clipforge.core.ids import uuid7
from clipforge.core.paths import SUBDIRS, ensure_data_dirs
from clipforge.db.base import UTCDateTime


def test_uuid7_version_and_order() -> None:
    a = uuid7()
    time.sleep(0.002)
    b = uuid7()
    assert a.version == 7 and b.version == 7
    assert a.variant == "specified in RFC 4122"
    assert a < b  # time-sortable


def test_uuid7_unique() -> None:
    assert len({uuid7() for _ in range(5000)}) == 5000


def test_data_dirs_created(tmp_path: Path) -> None:
    out = ensure_data_dirs(tmp_path / "d")
    for name in SUBDIRS:
        assert out[name].is_dir()


def test_utc_datetime_roundtrip_sqlite() -> None:
    from sqlalchemy.dialects import sqlite

    t = UTCDateTime()
    aware = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    stored = t.process_bind_param(aware, sqlite.dialect())
    assert stored is not None and stored.tzinfo is None
    back = t.process_result_value(stored, sqlite.dialect())
    assert back == aware and back.tzinfo is UTC


def test_utc_datetime_rejects_naive() -> None:
    from sqlalchemy.dialects import sqlite

    with pytest.raises(ValueError, match="naive"):
        UTCDateTime().process_bind_param(datetime(2026, 1, 1), sqlite.dialect())


def test_doctor_flags_missing_ffmpeg(tmp_path: Path) -> None:
    p = system.SystemProfile(
        os="x",
        python="3.12.1",
        cpu_cores=8,
        ram_gb=8,
        disk_free_gb=50,
        ffmpeg=None,
        ffprobe="7.0",
        light_mode_recommended=True,
    )
    checks = {c.name: c for c in system.doctor(p)}
    assert not checks["ffmpeg"].ok and checks["ffmpeg"].required
    assert checks["ffprobe"].ok
    assert not checks["ram"].ok and not checks["ram"].required
    assert not checks["gpu"].ok and not checks["gpu"].required


def test_profile_runs(tmp_path: Path) -> None:
    p = system.profile(tmp_path)
    assert p.cpu_cores >= 1 and p.ram_gb > 0 and p.disk_free_gb > 0
