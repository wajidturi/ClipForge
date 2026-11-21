"""Rendering: one pick -> one finished vertical MP4.

    segment.mp4 --(EDL: cut silences/fillers)--> edited.mkv
    edited.mkv --(reframe + zoom + captions + hook + loudness)--> short.mp4 (+ cover.jpg)

Pass 1 (edit) produces a compact timeline; everything after it (face analysis,
captions, zoom peaks) works in that output timeline, so no time mapping is
needed downstream except through `Edl.map`.
"""
