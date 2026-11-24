# 07 — Backend, AI & Video Processing Plan

How each engine works. Thresholds below are starting values, all configurable and tuned with the evaluation set (08).

## 1. Job system
- `enqueue(type, payload, caps, priority, parent, cache_key)`; workers `lease` with `UPDATE … WHERE status='queued' … LIMIT 1` (Postgres `FOR UPDATE SKIP LOCKED`; SQLite single-writer transaction), lease 60 s renewed by heartbeat.
- Failure → exponential backoff retry up to `max_attempts`; poison jobs marked failed with log.
- Cancellation flag checked between steps and inside long FFmpeg runs (process killed).
- Cache: step outputs stored under `cache/<cache_key>`; identical inputs skip work (e.g. re-render with only a new hook reuses reframe plan).
- Crash recovery: expired leases return to queue on startup.

## 2. Ingestion
- **Resolver:** classify URL → platform, external id; local file → probe with ffprobe.
- **Metadata:** yt-dlp `--dump-json` (title, channel, duration, upload date, language hint, chapters, heatmap).
- **Audio download:** bestaudio → m4a; window via `--download-sections`; long streams default to a configurable window (videos up to 12 h are used whole; longer ones default to the last 2 h).
- **Segment download for render:** best video ≤1080p for `[start−3 s, end+3 s]`.
- **Discovery:** RSS feeds (YouTube channel feeds), yt-dlp search (`ytsearchN:`), Twitch category top VODs (public GQL/Helix with own client id), filters (regex, language, ≤ max duration, not used).
- **Robustness:** retries with jitter, timeouts, cookies-from-browser option, yt-dlp self-update command in Settings, clear error→fix hints.

## 3. Transcription
- faster-whisper; device auto: CUDA float16 (model `small` default, `large-v3-turbo` optional) else CPU int8 (`base`); VAD filter on; `word_timestamps=True`.
- Language: detect on first 30 s; store probability; mismatch with user language → flag/skip per settings.
- Sentence builder: punctuation + pause > 0.6 s + max 20 words.
- Long sources processed in chunks with overlap; progress events per chunk.
- Output: `words.json` (start, end, word, prob) + `segments` rows.

## 4. Signals → HEAT
| Signal | Method |
|---|---|
| Loudness | ffmpeg `ebur128` momentary loudness per 0.5 s; rolling median baseline; spike = +X dB (start 8 dB) sustained ≥1 s → `LOUD +NdB` |
| Laughter / screams | band energy + zero-crossing heuristics; later optional small audio classifier (YAMNet ONNX) |
| Chat replay | Twitch VOD comments (GQL), YouTube live-chat replay (continuation API), Kick chat history; messages/10 s; spike = rate ≥ 3× rolling baseline and ≥ min; top phrases via n-gram counts, emote normalisation, bot filtering |
| Viewer clips | Twitch clips for the VOD (offset + views) → `CLIPPED xN views` |
| Replay heat | yt-dlp `heatmap` (YouTube "most replayed") → `REPLAYED xN` |
| Visual moments | 2 fps proxy (360p); features: motion energy (frame diff/optical flow magnitude), cut rate, face expression change (landmark deltas), audio energy; rule-based classifier → chase/crash/fight/stunt/reaction/funny with score |
| Banners | RapidOCR on centred band of frames at 1 fps; match a configurable word list per game (e.g. WASTED, BUSTED, MISSION PASSED) → `GAME <word>` |
| Shot cuts | PySceneDetect content detector (+ dissolve detection via histogram) |
| **HEAT** | per sentence: weighted sum of normalised signals (weights in settings), clipped 0–100; two co-occurring signals get a bonus |

## 5. Selection
- **Windows:** slide over sentences; window = sentence-aligned span 12–60 s (story-length, not fixed); score = max+mean heat, tag diversity, premise-before-peak heuristic (noun/named entity before spike), penalty for pronoun/conjunction openers and menu/silence.
- **Candidates:** top K (30, expandable to 60) with head…tail text.
- **Free mode:** greedy pick by score with constraints (no overlap, a fair share per source, distinct points via text similarity), rule-based hook from top keywords.
- **Smart/Deep (AI):** one structured request per run:
  - System prompt (cached, stable): selection rules (premise+payoff, picture-first, topic only, no spoilers/leaks, credit, stands alone, reveal in last 40 %, length follows story), text rules (hook ≤6 words caps, title ≤70 chars, 3–5 hashtags, keywords).
  - User content: candidates (Smart) or full transcripts with tags (Deep), user's topic/language, N. Transcript/chat text is wrapped as data, never instructions.
  - Output schema (Pydantic → JSON schema): `[{source_id, start, end, parts?, format, hook, title, hashtags[], keywords[], credit, score, reason}]`.
  - Validation: snap to sentences, talk-time ≥ 12 s after silence removal (else widen or replace), overlap/used-range checks, per-source cap; invalid items are sent back once for correction.
- **Callback finder:** for each high-heat payoff, search 1 min–3 h earlier for the same noun in claim patterns ("I bet", "watch", "I told you", repeated 3+×); returns candidate pairs to the AI/user.
- **Preview filter:** 4 frames per pick (240p); optional vision check (AI with images, or heuristics: menu/static-card/no-face detection) drops bad picks.

## 6. Rendering
- **Reframe:** per shot, sample frames at 4–6 fps; MediaPipe face + pose (+ YuNet fallback); subject = speaking/largest/most-central face, track with Kalman smoothing, dead-zone to avoid jitter, max pan speed; cam box detection by persistent face in a stable rectangle across shots + edge detection.
  - Layout decision: cam box + gameplay → `stack` (cam top 1/3, game bottom 2/3) or `bubble` (circle mask); no cam → tracked crop; multiple faces/grid → `full` (fit + blurred background) or call-grid tiles.
  - Clutter/overlay crop: detect static overlay regions (low temporal variance at frame edges) and letterboxing (`cropdetect`).
- **Speech editing:** keep-spans from words; cut gaps > 0.35 s down to 0.12 s, remove standalone fillers; tail trim after payoff; "wait-for-it" squeeze compresses silent build-up.
- **Zoom:** detect peaks (loudness + heat) → 1.0→1.12 punch-in over 0.2 s, optional flash/whoosh.
- **Captions:** ASS generator with style registry (≈30 styles as data: font, size, colours, box, outline, animation tags: karaoke `\k`, pop scale, shake, typewriter, slide); 1–3 words per group; keyword colour; position auto avoids detected faces; RTL/CJK shaping via libass + Noto fonts; emoji via colour emoji font if present.
- **Hook & overlays:** hook banner first N seconds (theme colours), watermark (static or bounce path), progress bar (`drawbox` width expression), end card, format cards (EARLIER tag, "X MINUTES LATER", numbered #3→#1, STRIKE n, THEN/NOW, WAIT FOR IT bar, chat bubbles rendered as PNGs).
- **Audio:** `afftdn` light denoise, voice/music ducking via `sidechaincompress`, SFX synthesised in numpy (boom, airhorn, trombone, scratch, crickets, heartbeat, rimshot, bass drop, ding, whoosh) and music beds (simple synth loops per mood), loudnorm 2-pass → −14 LUFS, true peak −1 dB.
- **Image fixes:** dark-cam lift (measure luma in cam box → gamma/curves), black-flash & frozen-frame cover (detect via `blackdetect`/`freezedetect`, replace with neighbouring frame/crossfade).
- **Encode:** one `filter_complex` graph; `h264_nvenc` (p5, cq 21) when available else `libx264 -preset medium -crf 20`; 1080×1920 @ source fps capped 60 (30 in light mode); AAC 192k; `+faststart`. Extra 4:5 / 1:1 from the same plan.
- **Cover:** best frame (face + expression, sharpness) + hook text.
- **Translation:** CTranslate2 OPUS-MT per language pair; translate per sentence, redistribute timing across words proportionally; CJK chunking by characters.
- **Voice:** align uploaded line at T, normalise, duck original by ~18 dB under it.

## 7. QC (per version)
Checks: duration in range; integrated loudness −14±1.5 LUFS; black frames/freezes (> 0.5 s) → WARN/FAIL; first frame not a menu/card (static + low face score); last 1 s still content (not logo/end card); caption word coverage ≥ 90 % of speech; face visible when layout expects it; captions not over faces. Verdict + human-readable reasons. FAIL → one automatic re-cut (shift boundary by a sentence), re-check, else mark dropped.

## 8. AI edit (natural language)
Claude with **strict tools** describing allowed edit operations: `trim(start_delta,end_delta)`, `set_hook(text)`, `set_title`, `set_style(name)`, `set_layout(name)`, `set_position`, `add_meme(mood,at?)`, `set_music(mood,level)`, `set_caption_word(idx,text)`, `set_keywords([..])`, `set_format(...)`, `crop_focus(t, x)`. The model returns tool calls → validated → shown to the user as a plan → applied → new version rendered. No free-form code or shell execution.

## 9. Live
- Recorder: streamlink → ffmpeg segmenter (`-f segment -segment_time 10`) into a ring buffer (keep last 10 min).
- Chat: Twitch IRC anonymous (`justinfan` nick over WebSocket), Kick Pusher channel, YouTube live chat polling; rate per minute, rolling baseline; spike when rate ≥ ratio×baseline and ≥ min (defaults 3× / 15 per min); cooldown.
- On spike: cut `[t−25 s, t+10 s]` from buffer → transcribe → candidate (+ chat top lines) → AI or user keeps/discards → render.
- Hunt: periodic "who's live" check for watched creators; start/stop sessions automatically if enabled.

## 10. Scheduling & publishing
- Planner spreads approved Shorts across chosen hours/days with min gap; stores UTC + display timezone.
- Publisher interface: `preview(entry)`, `send(entry)`, `status(entry)`. First implementation: YouTube Data API upload (resumable, Shorts metadata). Others plug in later.
- APScheduler triggers due sends **only for entries the user confirmed**; results/errors written back; post metrics fetched later for Insights.

## 11. Insights & learning
- Channel stats via YouTube Data API (user's own key/OAuth); per-Short diagnosis (retention, views vs channel median) → AI suggestions (structured).
- Learning: correlate past Shorts' features (format, length, hook pattern, signals) with performance → simple ranked rules that adjust selection weights (needs ≥ 8 posted Shorts).

## 12. System profile / light mode
Detect RAM/GPU/VRAM/disk at startup; under 12 GB RAM → 1 render worker, 30 fps, window cap 1 h, smaller Whisper model; disk guard refuses new runs below a threshold.
