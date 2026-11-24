"""`clipforge` command line.

clipforge dev            api + workers together (development / desktop use)
clipforge api            HTTP API only
clipforge worker         one worker process (--caps cpu,net[,gpu])
clipforge doctor         check the machine
clipforge db upgrade     apply migrations (also done automatically by `api`)
clipforge openapi        print the OpenAPI schema (used to generate TS types)
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from types import FrameType

from clipforge.core.config import get_settings
from clipforge.core.logging import configure_logging


def _api(args: argparse.Namespace) -> None:
    import uvicorn

    from clipforge.api.app import create_app

    s = get_settings()
    uvicorn.run(
        create_app(s),
        host=args.host or s.host,
        port=args.port or s.port,
        log_level=s.log_level.lower(),
    )


def _worker(args: argparse.Namespace) -> None:
    from clipforge.db import migrate
    from clipforge.jobs.worker import Worker

    s = get_settings()
    configure_logging(s.log_level, s.log_format)
    migrate.upgrade(s.resolved_database_url)
    w = Worker(worker_id=args.id, caps=[c.strip() for c in args.caps.split(",") if c.strip()])

    def stop(_sig: int, _frame: FrameType | None) -> None:
        w.stop.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    w.run_forever()


def _dev(args: argparse.Namespace) -> None:
    """Start the API and N workers as child processes; Ctrl+C stops them all."""
    from clipforge.db import migrate

    s = get_settings()
    configure_logging(s.log_level, s.log_format)
    migrate.upgrade(s.resolved_database_url)  # once, before children race for it
    exe = [sys.executable, "-m", "clipforge.cli"]
    n = s.workers if args.workers is None else args.workers
    api = subprocess.Popen([*exe, "api", "--port", str(args.port or s.port)])
    # The first `ml_workers` workers may also run ML jobs (transcription, vision);
    # keeping that number small bounds GPU memory and CPU load.
    ml = min(s.ml_workers, n)

    def spawn(i: int) -> subprocess.Popen[bytes]:
        caps = args.caps + (",ml" if i < ml else "")
        return subprocess.Popen([*exe, "worker", "--id", f"dev-{i + 1}", "--caps", caps])

    workers = [spawn(i) for i in range(n)]
    print(
        f"ClipForge running: http://{s.host}:{args.port or s.port}  ({n} workers, {ml} for ML)",
        flush=True,
    )
    try:
        # A worker exits when a stopped job had to be ended by force (or if it
        # crashed): start a fresh one. The app stops when the API stops.
        while api.poll() is None:
            for i, w in enumerate(workers):
                if w.poll() is not None:
                    print(
                        f"worker dev-{i + 1} exited ({w.returncode}); starting a new one",
                        flush=True,
                    )
                    time.sleep(1.0)  # no tight loop if it cannot start at all
                    workers[i] = spawn(i)
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        procs = [api, *workers]
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


def _doctor(_args: argparse.Namespace) -> None:
    from clipforge.core import system

    s = get_settings()
    p = system.profile(s.resolved_data_dir)
    ok = True
    for c in system.doctor(p):
        mark = "OK  " if c.ok else ("FAIL" if c.required else "WARN")
        print(f"[{mark}] {c.name:8} {c.detail}")
        if not c.ok and c.fix:
            print(f"         fix: {c.fix}")
        ok = ok and (c.ok or not c.required)
    sys.exit(0 if ok else 1)


def _db(args: argparse.Namespace) -> None:
    from clipforge.db import migrate

    url = get_settings().resolved_database_url
    if args.action == "upgrade":
        migrate.upgrade(url)
    else:
        migrate.downgrade(url, args.revision)
    print(f"database {args.action}d: {url.split('@')[-1]}")


def _openapi(args: argparse.Namespace) -> None:
    from clipforge.api.app import create_app

    schema = create_app(run_migrations=False).openapi()
    text = json.dumps(schema, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)


def _update_downloader(_args: argparse.Namespace) -> None:
    """Sites change often; a newer yt-dlp usually fixes 'no formats'/'unsupported' errors."""
    import shutil as _sh

    import yt_dlp

    uv = _sh.which("uv")
    before = yt_dlp.version.__version__
    cmd = (
        [uv, "pip", "install", "--python", sys.executable, "-U", "yt-dlp[default,deno]"]
        if uv
        else [sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default,deno]"]
    )
    code = subprocess.call(cmd)
    after = subprocess.run(
        [sys.executable, "-c", "import yt_dlp;print(yt_dlp.version.__version__)"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    print(f"yt-dlp {before} -> {after or '?'}")
    sys.exit(code)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="clipforge")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("api", help="run the HTTP API")
    a.add_argument("--host")
    a.add_argument("--port", type=int)
    a.set_defaults(fn=_api)

    w = sub.add_parser("worker", help="run one worker")
    w.add_argument("--id")
    w.add_argument("--caps", default="cpu,net")
    w.set_defaults(fn=_worker)

    d = sub.add_parser("dev", help="run api + workers")
    d.add_argument("--port", type=int)
    d.add_argument("--workers", type=int)
    d.add_argument("--caps", default="cpu,net")
    d.set_defaults(fn=_dev)

    sub.add_parser("doctor", help="check this machine").set_defaults(fn=_doctor)

    db = sub.add_parser("db", help="database migrations")
    db.add_argument("action", choices=["upgrade", "downgrade"])
    db.add_argument("--revision", default="base")
    db.set_defaults(fn=_db)

    sub.add_parser(
        "update-downloader", help="update yt-dlp (fixes most download errors)"
    ).set_defaults(fn=_update_downloader)

    o = sub.add_parser("openapi", help="print the OpenAPI schema")
    o.add_argument("--out")
    o.set_defaults(fn=_openapi)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
