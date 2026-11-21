"""Alembic environment. URL priority: explicit config attribute (tests) -> settings."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

from clipforge.core.config import get_settings
from clipforge.db import models  # noqa: F401  (registers tables on Base.metadata)
from clipforge.db.base import Base
from clipforge.db.session import make_engine

config = context.config
if config.config_file_name and not config.attributes.get("skip_logging"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    url = config.attributes.get("url") or config.get_main_option("sqlalchemy.url")
    if url:
        return str(url)
    settings = get_settings()
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    return settings.resolved_database_url


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    is_sqlite = (url or str(connection.engine.url if connection else "")).startswith("sqlite")
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        render_as_batch=is_sqlite,  # SQLite needs table rebuilds for ALTER
        compare_type=True,
        literal_binds=url is not None,
    )


def run_offline() -> None:
    _configure(url=_url())
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = make_engine(_url())
    with engine.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
