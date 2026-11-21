"""Programmatic Alembic helpers used by the CLI, the app startup and tests."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[3]


def alembic_config(url: str | None = None) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["skip_logging"] = True
    if url:
        cfg.attributes["url"] = url
    return cfg


def ensure_sqlite_dir(url: str | None) -> None:
    """SQLite cannot create a database file inside a folder that does not exist yet."""
    if url and url.startswith("sqlite:///"):
        db_path = make_url(url).database
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def upgrade(url: str | None = None, revision: str = "head") -> None:
    ensure_sqlite_dir(url)
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str | None = None, revision: str = "base") -> None:
    ensure_sqlite_dir(url)
    command.downgrade(alembic_config(url), revision)
