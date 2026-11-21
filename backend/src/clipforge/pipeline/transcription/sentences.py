"""Group word timings into sentence-like segments (the unit of the transcript UI,
heat scoring and moment boundaries)."""

from __future__ import annotations

from dataclasses import dataclass

# Fullwidth marks end sentences in Chinese/Japanese transcripts (intentional).
END_PUNCT = (".", "?", "!", "…", "。", "？", "！")  # noqa: RUF001


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str  # includes the leading space whisper emits, e.g. " hello"
    prob: float = 1.0


@dataclass(frozen=True)
class Sentence:
    start: float
    end: float
    text: str
    first_word: int  # index into the word list
    last_word: int  # inclusive


def build_sentences(
    words: list[Word],
    *,
    max_gap: float = 0.6,
    max_words: int = 20,
    max_duration: float = 15.0,
) -> list[Sentence]:
    """Split on sentence punctuation, on pauses longer than `max_gap`, or when a
    sentence grows past `max_words` / `max_duration` (long run-on speech)."""
    out: list[Sentence] = []
    start_idx = 0

    def flush(end_idx: int) -> None:
        nonlocal start_idx
        if end_idx < start_idx:
            return
        chunk = words[start_idx : end_idx + 1]
        text = "".join(w.text for w in chunk).strip()
        if text:
            out.append(Sentence(chunk[0].start, chunk[-1].end, text, start_idx, end_idx))
        start_idx = end_idx + 1

    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else None
        n_words = i - start_idx + 1
        duration = w.end - words[start_idx].start
        if (
            nxt is None
            or w.text.strip().endswith(END_PUNCT)
            or nxt.start - w.end > max_gap
            or n_words >= max_words
            or duration >= max_duration
        ):
            flush(i)
    return out
