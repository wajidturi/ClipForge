"""Real models (slow; downloads Whisper ~500 MB and MediaPipe ~4 MB on first run).

Run manually:  $env:CF_TEST_REAL_ML="1"; uv run pytest -m real_ml -s
Speech is generated with Windows' built-in text-to-speech, so the transcript test
only runs on Windows.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from clipforge.pipeline.signals import vision as vision_sig
from clipforge.pipeline.transcription.sentences import build_sentences
from clipforge.pipeline.transcription.whisper import Transcriber

pytestmark = [
    pytest.mark.real_ml,
    pytest.mark.skipif(os.environ.get("CF_TEST_REAL_ML") != "1", reason="set CF_TEST_REAL_ML=1"),
]

MODELS = Path(
    os.environ.get("CF_TEST_MODELS_DIR", Path(__file__).resolve().parents[2] / "data" / "models")
)
SENTENCE = "The red car crashed into the wall. Nobody expected that."


def speak(path: Path, text: str) -> Path:
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SetOutputToWaveFile('{path}'); $s.Speak('{text}'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=60)
    return path


@pytest.mark.skipif(sys.platform != "win32", reason="uses Windows text-to-speech")
def test_real_whisper_transcribes_speech(tmp_path: Path) -> None:
    wav = speak(tmp_path / "s.wav", SENTENCE)
    r = Transcriber(download_root=MODELS / "whisper").transcribe(wav)
    text = " ".join(s.text for s in build_sentences(r.words)).lower()
    assert r.language == "en" and "car crashed into the wall" in text and "expected" in text
    assert all(w.end >= w.start for w in r.words) and r.words[0].start < 1.0


def test_real_face_model_loads_and_runs() -> None:
    model = vision_sig.ensure_face_model(MODELS)
    faces = vision_sig._Faces(model)
    try:
        blank = np.full((360, 640, 3), 128, dtype=np.uint8)
        assert faces.expression(blank, 0) is None  # no face in a grey frame
    finally:
        faces.close()
