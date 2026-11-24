"""Ending the programs a job started (FFmpeg, yt-dlp's FFmpeg, Deno...).

A worker runs one job at a time, so every child process it started after the job
began belongs to that job. Stopping a job ends them all, children of children too.
"""

from __future__ import annotations

import contextlib
import os

import psutil

from clipforge.core.logging import get_logger

log = get_logger(__name__)


def job_children(since: float, pid: int | None = None) -> list[psutil.Process]:
    """Child processes (recursive) of `pid` (default: this process) started at or after
    `since` (a `time.time()` value)."""
    try:
        kids = psutil.Process(pid or os.getpid()).children(recursive=True)
    except psutil.Error:
        return []
    out = []
    for p in kids:
        try:
            if p.create_time() >= since - 1.0:  # create_time has ~1 s resolution on some OSes
                out.append(p)
        except psutil.Error:
            continue
    return out


def kill_job_children(since: float, pid: int | None = None, timeout: float = 3.0) -> int:
    """Terminate, then kill what is left. Returns how many processes were ended."""
    procs = job_children(since, pid)
    if not procs:
        return 0
    names = sorted({_name(p) for p in procs})  # before they are gone
    for p in procs:
        with contextlib.suppress(psutil.Error):
            p.terminate()
    _, alive = psutil.wait_procs(procs, timeout=timeout)
    for p in alive:
        with contextlib.suppress(psutil.Error):
            p.kill()
    psutil.wait_procs(alive, timeout=timeout)
    log.info("job.children_ended", count=len(procs), names=names)
    return len(procs)


def _name(p: psutil.Process) -> str:
    try:
        return str(p.name())
    except psutil.Error:
        return "?"
