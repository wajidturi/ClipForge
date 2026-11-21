"""Cues in the words themselves: laughter and strong reactions.

Whisper often writes laughter as "haha", "(laughs)" or "[Laughter]". Exclamations
like "no way", "oh my god", "let's go" mark reactions. Cheap and language-light;
the AI picker (Phase 4) judges meaning, this only points at candidates.
"""

from __future__ import annotations

import re

from clipforge.pipeline.signals import Spike
from clipforge.pipeline.transcription.sentences import Sentence

LAUGH = re.compile(
    r"\b(?:a?ha(?:ha)+h?|ha(?:[\s,-]+ha)+|he(?:he)+|lol|lmao+|lmfao|rofl)\b"
    r"|[\(\[]\s*(?:laugh\w*|chuckl\w*|giggl\w*)\s*[\)\]]",
    re.I,
)
REACTION = re.compile(
    r"\b(?:no way|oh my god|oh my gosh|omg|what the (?:hell|heck|fuck)|wtf|let'?s go+|"
    r"are you serious|holy (?:shit|crap|moly)|no no no|yes yes yes|oh no|bro what|"
    r"i can'?t believe)\b",
    re.I,
)
SCREAM = re.compile(r"\b(?:a{3,}h*|no{3,}|ye+s{3,})\b|!{2,}", re.I)


def text_spikes(sentences: list[Sentence]) -> list[Spike]:
    out: list[Spike] = []
    for s in sentences:
        if m := LAUGH.search(s.text):
            out.append(Spike("laugh", s.start, s.end, 0.7, "laughter", {"match": m.group(0)}))
        elif m := REACTION.search(s.text):
            out.append(
                Spike("moment", s.start, s.end, 0.5, "reaction words", {"match": m.group(0)})
            )
        elif m := SCREAM.search(s.text):
            out.append(Spike("moment", s.start, s.end, 0.4, "shouting", {"match": m.group(0)}))
    return out
