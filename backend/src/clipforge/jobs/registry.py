"""Job handler registry and the context object handlers receive.

A handler is a plain function `(ctx, payload) -> result dict`. It reports progress
with `ctx.progress()`, and calls `ctx.check_cancelled()` between steps so a user's
cancel takes effect quickly. Long subprocesses (FFmpeg) will poll `ctx.cancelled`.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clipforge.core.logging import get_logger

log = get_logger(__name__)


class JobCancelledError(Exception):
    """Raised inside a handler when the user cancelled the job."""


class PermanentJobError(Exception):
    """A failure that retrying cannot fix (bad input, unsupported source...)."""


ProgressFn = Callable[[float | None, str | None], None]


@dataclass
class JobContext:
    job_id: uuid.UUID
    attempt: int
    data_dir: Path
    _progress: ProgressFn
    max_attempts: int = 1
    _cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def is_last_attempt(self) -> bool:
        return self.attempt >= self.max_attempts

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def request_cancel(self) -> None:
        self._cancel.set()

    def check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise JobCancelledError

    def progress(self, pct: float | None, step: str | None = None) -> None:
        """pct None = unknown (only the step text changes)."""
        self._progress(pct, step)

    def sleep(self, seconds: float) -> None:
        """Cancellable sleep."""
        if self._cancel.wait(seconds):
            raise JobCancelledError


Handler = Callable[[JobContext, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class JobSpec:
    type: str
    handler: Handler
    caps: tuple[str, ...]
    public: bool  # may be started directly through POST /api/v1/jobs
    description: str


_REGISTRY: dict[str, JobSpec] = {}


def job_handler(
    type_: str, *, caps: tuple[str, ...] = ("cpu",), public: bool = False, description: str = ""
) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        if type_ in _REGISTRY:
            raise ValueError(f"duplicate job handler: {type_}")
        _REGISTRY[type_] = JobSpec(type_, fn, caps, public, description or (fn.__doc__ or ""))
        return fn

    return deco


def get_spec(type_: str) -> JobSpec | None:
    load_handlers()
    return _REGISTRY.get(type_)


def all_specs() -> list[JobSpec]:
    load_handlers()
    return sorted(_REGISTRY.values(), key=lambda s: s.type)


_loaded = False


def load_handlers() -> None:
    """Import handler modules once so their decorators register."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    from clipforge.jobs.handlers import ingest, system  # noqa: F401
