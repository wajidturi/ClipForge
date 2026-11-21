"""Server -> browser event fan-out.

Workers are separate processes and only write to the database, so the API watches
tables for rows whose `updated_at` moved and pushes them to every open WebSocket.
Local mode polls every 0.5 s (one cheap indexed query per watched table, only while
a browser is connected). Server mode can swap this for PostgreSQL LISTEN/NOTIFY
without touching the WebSocket code. See docs/adr/0003-realtime-events.md.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from clipforge.api.schemas import (
    JobEvent,
    JobOut,
    RunEvent,
    RunOut,
    ShortEvent,
    SourceEvent,
    SourceOut,
)
from clipforge.core.logging import get_logger
from clipforge.db.base import utcnow
from clipforge.db.models import Job, Run, Short, Source
from clipforge.db.session import get_sessionmaker

log = get_logger(__name__)


@dataclass
class Watch:
    model: Any  # ORM class with an `updated_at` column
    to_event: Callable[[Any], BaseModel]
    cursor: datetime = field(default_factory=lambda: utcnow() - timedelta(seconds=1))


def default_watches() -> list[Watch]:
    return [
        Watch(Job, lambda r: JobEvent(job=JobOut.model_validate(r))),
        Watch(Source, lambda r: SourceEvent(source=SourceOut.model_validate(r))),
        Watch(Run, lambda r: RunEvent(run=RunOut.model_validate(r))),
        Watch(Short, lambda r: ShortEvent(id=r.id, run_id=r.run_id, status=r.status)),
    ]


class EventHub:
    def __init__(self, poll_interval: float = 0.5, watches: list[Watch] | None = None) -> None:
        self.poll_interval = poll_interval
        self.watches = watches if watches is not None else default_watches()
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._task: asyncio.Task[None] | None = None

    # -------------------------------------------------------------- subscribers
    def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        self._subscribers.discard(q)

    def publish(self, message: str) -> None:
        for q in list(self._subscribers):
            if q.full():  # slow client: drop its oldest message rather than block everyone
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(message)

    def publish_model(self, event: BaseModel) -> None:
        """For events that are not row updates (e.g. deletions), sent by the API itself."""
        self.publish(event.model_dump_json())

    # -------------------------------------------------------------- watcher
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._watch(), name="event-hub")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def _changes(self) -> list[str]:
        out: list[str] = []
        with get_sessionmaker()() as s:
            for w in self.watches:
                rows = s.scalars(
                    select(w.model)
                    .where(w.model.updated_at > w.cursor)
                    .order_by(w.model.updated_at)
                    .limit(500)
                ).all()
                if rows:
                    w.cursor = rows[-1].updated_at
                out.extend(w.to_event(r).model_dump_json() for r in rows)
        return out

    async def _watch(self) -> None:
        while True:
            try:
                if self._subscribers:
                    for msg in await run_in_threadpool(self._changes):
                        self.publish(msg)
                else:
                    for w in self.watches:  # nobody listening: skip history
                        w.cursor = utcnow()
            except Exception as e:
                log.warning("events.poll_error", error=str(e))
            await asyncio.sleep(self.poll_interval)
