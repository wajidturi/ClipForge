"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from clipforge import __version__
from clipforge.api import routes_jobs, routes_media, routes_runs, routes_sources, routes_system
from clipforge.api.events import EventHub
from clipforge.core.config import Settings, get_settings
from clipforge.core.logging import configure_logging, get_logger
from clipforge.core.paths import ensure_data_dirs
from clipforge.db import migrate

log = get_logger(__name__)
API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, *, run_migrations: bool = True) -> FastAPI:
    settings = settings or get_settings()
    hub = EventHub(settings.event_poll_interval)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level, settings.log_format)
        ensure_data_dirs(settings.resolved_data_dir)
        if run_migrations:
            await asyncio.to_thread(migrate.upgrade, settings.resolved_database_url)
        hub.start()
        log.info("api.start", data_dir=str(settings.resolved_data_dir), version=__version__)
        yield
        await hub.stop()

    app = FastAPI(
        title="ClipForge API",
        version=__version__,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.state.hub = hub

    # Vite dev server runs on another port during development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(routes_system.router)
    api.include_router(routes_jobs.router)
    api.include_router(routes_sources.router)
    api.include_router(routes_media.router)
    api.include_router(routes_runs.router)

    @api.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        await socket.accept()
        q = hub.subscribe()

        async def drain_client() -> None:
            while True:  # we only need to notice disconnects; client messages are ignored
                await socket.receive_text()

        reader = asyncio.create_task(drain_client())
        try:
            while not reader.done():
                with contextlib.suppress(TimeoutError):
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    await socket.send_text(msg)
                    continue
                await socket.send_text('{"type":"ping"}')
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            reader.cancel()
            hub.unsubscribe(q)

    app.include_router(api)
    _mount_frontend(app, settings.frontend_dist)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built SPA (production). Unknown paths fall back to index.html."""
    index = dist / "index.html"
    if not index.exists():
        return
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)
