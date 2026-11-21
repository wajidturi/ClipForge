"""Local speech-to-text with word timestamps (faster-whisper / CTranslate2).

- GPU (CUDA, float16) when available, model `small`; otherwise CPU int8, model `base`.
- If CUDA libraries fail at load or first use, we fall back to CPU once and say so.
- Models download on first use into <data>/models/whisper and stay warm per process.
- Silero VAD skips silence, which both speeds things up and avoids hallucinated text.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clipforge.core.logging import get_logger
from clipforge.pipeline.transcription.cuda import cuda_device_count, setup_cuda_libraries
from clipforge.pipeline.transcription.sentences import Word

log = get_logger(__name__)

# Windows without Developer Mode cannot symlink; the model cache copies instead. Harmless.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

GPU_DEFAULT_MODEL = "small"
CPU_DEFAULT_MODEL = "base"
CUDA_ERRORS = ("cublas", "cudnn", "cuda", "libcudart", "ctranslate2 was not compiled")


class TranscriptionCancelledError(Exception):
    pass


@dataclass
class TranscribeResult:
    words: list[Word]
    language: str | None
    language_prob: float | None
    model: str
    device: str
    audio_duration_s: float | None
    notes: list[str] = field(default_factory=list)


def pick_device(requested: str = "auto") -> str:
    if requested in ("cpu", "cuda"):
        return requested
    return "cuda" if cuda_device_count() > 0 else "cpu"


_models: dict[tuple[str, str, str], Any] = {}
_lock = threading.Lock()


def _load(model: str, device: str, compute_type: str, download_root: Path) -> Any:
    from faster_whisper import WhisperModel

    key = (model, device, compute_type)
    with _lock:
        if key not in _models:
            if device == "cuda":
                setup_cuda_libraries()
            log.info("whisper.load", model=model, device=device, compute_type=compute_type)
            _models[key] = WhisperModel(
                model, device=device, compute_type=compute_type, download_root=str(download_root)
            )
        return _models[key]


class Transcriber:
    def __init__(
        self,
        *,
        model: str | None = None,
        device: str = "auto",
        download_root: Path,
        loader: Callable[[str, str, str, Path], Any] = _load,
    ) -> None:
        self.device = pick_device(device)
        self.model = model or (GPU_DEFAULT_MODEL if self.device == "cuda" else CPU_DEFAULT_MODEL)
        self.download_root = download_root
        self.loader = loader

    def _compute_type(self, device: str) -> str:
        return "float16" if device == "cuda" else "int8"

    def transcribe(
        self,
        audio: Path,
        *,
        language: str | None = None,
        progress: Callable[[float, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> TranscribeResult:
        notes: list[str] = []
        try:
            return self._run(self.device, audio, language, progress, is_cancelled, notes)
        except TranscriptionCancelledError:
            raise
        except Exception as e:
            if self.device != "cuda" or not any(k in str(e).lower() for k in CUDA_ERRORS):
                raise
            msg = f"GPU transcription failed ({str(e)[:160]}); using the CPU instead (slower)."
            log.warning("whisper.cuda_fallback", error=str(e))
            notes.append(msg)
            self.device, self.model = "cpu", CPU_DEFAULT_MODEL
            return self._run("cpu", audio, language, progress, is_cancelled, notes)

    def _run(
        self,
        device: str,
        audio: Path,
        language: str | None,
        progress: Callable[[float, str], None] | None,
        is_cancelled: Callable[[], bool] | None,
        notes: list[str],
    ) -> TranscribeResult:
        if progress:
            progress(0, f"loading speech model ({self.model}, {device.upper()})")
        model = self.loader(self.model, device, self._compute_type(device), self.download_root)
        segments, info = model.transcribe(
            str(audio),
            language=language,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            beam_size=5,
            condition_on_previous_text=False,  # avoids repetition loops on long audio
        )
        total = float(getattr(info, "duration", 0) or 0)
        words: list[Word] = []
        for seg in segments:  # generator: decoding happens while we iterate
            if is_cancelled and is_cancelled():
                raise TranscriptionCancelledError
            for w in seg.words or []:
                words.append(Word(float(w.start), float(w.end), w.word, float(w.probability)))
            if progress and total:
                done = min(seg.end, total)
                progress(
                    min(99.0, done / total * 100), f"transcribing {_clock(done)} of {_clock(total)}"
                )
        return TranscribeResult(
            words=words,
            language=getattr(info, "language", None),
            language_prob=getattr(info, "language_probability", None),
            model=self.model,
            device=device,
            audio_duration_s=total or None,
            notes=notes,
        )


def _clock(s: float) -> str:
    s = int(s)
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
