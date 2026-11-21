from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect

from clipforge.core.config import get_settings
from clipforge.db import (
    migrate,
    models,  # noqa: F401
)
from clipforge.db.base import Base

EXPECTED = set(Base.metadata.tables)


def _tables(url: str) -> set[str]:
    eng = create_engine(url)
    try:
        return set(inspect(eng).get_table_names()) - {"alembic_version"}
    finally:
        eng.dispose()


def _roundtrip(url: str) -> None:
    migrate.upgrade(url)
    assert _tables(url) == EXPECTED
    migrate.downgrade(url, "base")
    assert _tables(url) == set()
    migrate.upgrade(url)  # upgrade again after a full downgrade
    assert _tables(url) == EXPECTED


def test_migrations_sqlite() -> None:
    _roundtrip(get_settings().resolved_database_url)


def test_models_match_migrations() -> None:
    """Autogenerate must find nothing to do: models and migrations are in sync."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    url = get_settings().resolved_database_url
    migrate.upgrade(url)
    eng = create_engine(url)
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    eng.dispose()
    assert diff == []


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("CF_TEST_POSTGRES_URL"), reason="CF_TEST_POSTGRES_URL not set"
)
def test_migrations_postgres() -> None:
    _roundtrip(os.environ["CF_TEST_POSTGRES_URL"])
