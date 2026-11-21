"""Make the pip-installed NVIDIA libraries (cuBLAS, cuDNN) findable by CTranslate2.

On Windows the DLLs live in site-packages/nvidia/<lib>/bin, which is not on the DLL
search path. We add those folders (and prepend PATH, which CTranslate2's plain
LoadLibrary uses). On Linux the loader reads LD_LIBRARY_PATH at process start, so
`docs/setup.md` documents exporting it; here we only report what is available.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from functools import lru_cache
from pathlib import Path

NVIDIA_PACKAGES = ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc")


def _lib_dirs() -> list[Path]:
    dirs: list[Path] = []
    for pkg in NVIDIA_PACKAGES:
        try:
            spec = importlib.util.find_spec(pkg)
        except (ImportError, ValueError):
            continue
        for loc in (spec.submodule_search_locations or []) if spec else []:
            for sub in ("bin", "lib"):
                d = Path(loc) / sub
                if d.is_dir():
                    dirs.append(d)
    return dirs


@lru_cache
def setup_cuda_libraries() -> list[str]:
    """Idempotent. Returns the folders that were added."""
    added = [str(d) for d in _lib_dirs()]
    if sys.platform == "win32":
        for d in added:
            os.add_dll_directory(d)
        if added:
            os.environ["PATH"] = os.pathsep.join([*added, os.environ.get("PATH", "")])
    return added


@lru_cache
def cuda_device_count() -> int:
    setup_cuda_libraries()
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0
