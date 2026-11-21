"""Media storage layout inside the data directory (see docs/05-database-design.md section 3)."""

from __future__ import annotations

from pathlib import Path

SUBDIRS = ("sources", "renders", "previews", "live", "cache", "models", "logs", "backups")


def ensure_data_dirs(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    out = {"root": root}
    for name in SUBDIRS:
        p = root / name
        p.mkdir(exist_ok=True)
        out[name] = p
    return out


def job_log_path(root: Path, job_id: str) -> Path:
    return root / "logs" / f"{job_id}.log"
