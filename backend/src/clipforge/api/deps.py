from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from clipforge.core.config import Settings, get_settings
from clipforge.db.session import get_sessionmaker


def db_session() -> Iterator[Session]:
    with get_sessionmaker()() as s:
        yield s


DB = Annotated[Session, Depends(db_session)]
Config = Annotated[Settings, Depends(get_settings)]
