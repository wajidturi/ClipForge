from __future__ import annotations

from pathlib import Path

import pytest

from clipforge.cli import main
from clipforge.core.config import get_settings
from clipforge.db.session import get_engine


def test_db_upgrade_on_fresh_machine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """First run: neither the data dir nor the database exists yet (regression test)."""
    data = tmp_path / "fresh" / "nested" / "data"
    monkeypatch.setenv("CF_DATA_DIR", str(data))
    monkeypatch.delenv("CF_DATABASE_URL")
    get_settings.cache_clear()
    get_engine.cache_clear()
    assert not data.exists()
    main(["db", "upgrade"])
    assert (data / "clipforge.db").is_file()
    assert "upgraded" in capsys.readouterr().out


def test_openapi_command(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    main(["openapi", "--out", str(out)])
    assert '"/api/v1/jobs"' in out.read_text(encoding="utf-8")
