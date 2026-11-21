# 01 — Reverse Engineering & Research Findings

**Status:** Phase 0 deliverable · **Date:** 2026-11-20
**Reference studied:** open-source "gta6-clipper" (MIT license, v1.0.15), read-only. Nothing from it was executed during research, and no code from it will be copied. We re-implement behaviour from scratch with our own design.

> **Legal note.** The reference is MIT-licensed, so studying it and building an independent implementation of the same *functionality* is allowed. We do not copy its source, assets (fonts, sounds, models, images) or text. Where we need the same kind of asset (e.g. open fonts, face-detection models) we obtain it from its original upstream under its own license.

---

## 1. Method

| Area | Tool used | Why |
|---|---|---|
| Frontend (single `app.html`, ~400 KB, inline JS) | **REA** `analyze_javascript_application` | Static AST graph of the UI script: call-flow, data-flow, request sites, timers |
| Frontend API surface | REA graph + targeted search over the extracted script | REA's route view returned no candidates because the UI calls the backend through its own `fetch` wrapper; literal `/api/...` strings were enumerated directly |
| Backend (25 Python modules, ~650 KB) | Source reading (module headers, function inventory, route table) | The REA skill itself says plain source is read with normal tools; REA's analyzers target JS/native/managed artifacts, not Python source |
| Workflow & processing logic | The reference's own operator docs (workflow + reference sheets) | They describe the end-to-end pipeline, rules and thresholds |

### REA evidence ledger

| Evidence ID | What it covers | Result |
|---|---|---|
| `ev_d957c4e5…` | Whole repo as a JS application | 11 JS files parsed; **limitation:** `app.html` inline script (line 137+) *not analyzed*; venv files polluted the scan |
| `ev_4be82be9…` | Extracted UI script `app.js` (1,221 lines) + `yt_panel.js` | 2/2 parsed, 37,212 AST nodes, 6,033 call-flow + 15,092 data-flow relations, **no network/child-process/storage APIs used directly** (all I/O goes through one wrapper), 4 timer sites (polling) |
| `ev_8cfd4802…` | Route view of the same | Empty: confirms routes are built through the wrapper, not literal `fetch()` calls |

**Observed vs inferred:** everything in §2–§4 is observed in source/text. Behaviour at runtime (speeds, quality) is *not* observed; numbers like "~85× realtime" come from the reference's own comments and are treated as claims to verify.

---

## 2. What the reference application is

A **local-first, AI-assisted "long video → vertical Shorts" factory**:

1. Find source videos (channel RSS, search, Twitch category, or a user link/file).
2. Download audio only, transcribe locally with word timestamps.
3. Enrich the transcript with *signals*: loudness spikes, chat spikes, viewer-clip hotspots, replay hotspots, visual moment labels, on-screen game banners → one **HEAT** score.
4. Rank candidate windows; an **AI (or a no-AI heuristic)** picks the best moments and writes hook/title/hashtags.
5. Download only the chosen segments, **auto-reframe 16:9 → 9:16** with face/subject tracking, cut dead air, burn word-by-word captions + hook, normalise loudness.
6. Optional "formats" (callback, compilation, wait-for-it…), meme sounds, music bed, voice-over, translation, watermark/branding.
7. Automatic **QC** (PASS/WARN/FAIL), contact-sheet overview.
8. A local web app to review/approve/reject, edit (incl. natural-language AI edits), re-render, schedule, and optionally publish through a third-party API.
9. **Live mode:** record a live stream in a rolling buffer and auto-clip on chat spikes.

### Architecture as found

```
Browser (single HTML page, vanilla JS, ~98 functions, polling)
   │  JSON over HTTP (60+ /api routes)
   ▼
app.py  — Python stdlib ThreadingHTTPServer, in-memory JOBS dict,
          state in one JSON file (app_state.json), spawns CLI scripts
   │  subprocess (python script.py …) / shells out to AI CLIs
   ▼
watch · transcribe · chat · moments · vision · nopick · batch · clip · reframe ·
formats · parts · meme · translate · voice · qc · peek · live · hunt · learn ·
callbacks · ytstats · update · lite
   │
   ▼
ffmpeg/ffprobe · yt-dlp · streamlink · faster-whisper · MediaPipe · OpenCV · Argos
```

---

## 3. Weaknesses we will NOT reproduce

| Reference design | Problem | Our approach |
|---|---|---|
| One JSON file as the database | No concurrency safety, no queries, corruption risk | Relational DB (SQLite WAL locally / PostgreSQL on server) with migrations |
| Jobs in a Python dict, lost on restart | No retry, no recovery, no history | Persistent job queue table + worker processes, resumable steps |
| AI by shelling out to whichever CLI is installed (8 providers) and parsing text | Fragile, hard to test, prompt injection surface | Provider interface over official SDK/HTTP APIs with **schema-validated structured output** |
| Single 400 KB HTML file, string-built DOM | Unmaintainable, no types, no tests | React + TypeScript SPA with components, routing, typed API client |
| Frontend polls every few seconds | Wasteful, laggy | WebSocket/SSE push for job progress |
| CLI scripts glued by files on disk (`picks.json`, `candidates.txt`) | Hidden contracts | Typed service layer; files only for media |
| Self-update from the author's server | Supply-chain risk | Normal versioned releases (installer / Docker image) |
| Hard-coded game/streamer focus | Narrow | Generic: any game, any creator, any niche; niche presets are data |

## 4. Content to strip (promotional / developer-specific)

- Affiliate/referral sign-up links for the posting service, "made by" banners, author handles, guide/download URLs, feedback URL env var, video promo `TODO`s.
- Author-hosted update manifest and changelog feed.
- Pre-seeded streamer lists and channel lists tied to one game and one date; demo screenshots/GIFs; example Shorts of real creators.
- "Propose a change" panel that sends feedback to the author.
- Bundled third-party CLI agent integrations that depend on the author's workflow (Antigravity/Kimi chain mode).

We keep the *capabilities* (e.g. a creator list, publishing integration) but ship them empty/neutral and configurable.

---

## 5. Source-to-feature map (what each reference module does)

| Module | Responsibility (re-implemented in our service named in brackets) |
|---|---|
| watch | Source discovery: YouTube RSS, search queries, Twitch category VODs; title/language/duration filters; audio-only download; skips already-used sources [`ingest`] |
| transcribe | faster-whisper with word timestamps, GPU→CPU fallback, model choice by device; loudness tags [`transcription`] |
| chat | Chat replay fetch (Twitch/YouTube/Kick), spike detection, top phrases, viewer-clip hotspots, replay heatmap, HEAT score; live chat readers (Twitch IRC anon, Kick Pusher, YouTube live) [`signals`] |
| moments | No-AI visual+audio labelling: chase/crash/fight/stunt/reaction/funny + banner events; webcam detection [`signals.vision`] |
| vision | OCR of big centred banners (WASTED, MISSION PASSED…), wanted-stars, hard cuts [`signals.vision`] |
| callbacks | Setup→payoff pair finder (claim earlier, spike later) [`selection`] |
| nopick | Window scoring from tags; candidate list (top-N); length/talk-time validation; no-AI picks [`selection`] |
| learn | Learns rules from the user's own channel Short performance (public metadata) [`insights`] |
| peek | 4-frame preview strip per pick from a 240p segment [`preview`] |
| batch | Validates picks, dedupes, max-per-source, parallel render, overview sheet, runs QC [`render.orchestrator`] |
| clip | Cut → reframe → silence/filler removal → zoom on peaks → captions (ASS) → hook → loudness −14 LUFS; dark-cam lift, freeze/black-flash cover, cover image, post text [`render.clip`] |
| reframe | Shot detection, person/face detection, subject tracking, layouts: crop/stack/bubble/full/call-grid, overlay/cam box detection, letterbox removal [`render.reframe`] |
| formats / parts | Multi-part formats: moment, callback, compilation, escalation, then-vs-now, reveal, chat overlay, wait-for-it; jump cards [`render.formats`] |
| meme | Synthesised SFX (vine boom, airhorn, trombone…), mood→effect mapping (freeze, push-in, shake, vignette), user-added sounds, synth music beds with ducking [`render.audiofx`] |
| translate | Offline caption/hook translation (Argos/CTranslate2), CJK chunking [`translation`] |
| voice | Insert user voice line at time T with ducking [`render.voice`] |
| qc | Duration, LUFS, black/freeze/card frames, word coverage, faces → PASS/WARN/FAIL [`qc`] |
| live / hunt | Live recording (rolling segments), chat spike → clip, "who is live now" across platforms, past-stream lists [`live`] |
| ytstats | YouTube Data/Analytics (own keys, OAuth) → diagnosis of a Short's performance + AI ideas [`insights`] |
| lite | Low-RAM mode: 1 worker, 30 fps, limited duration [`system.profile`] |
| app (server) | 60+ endpoints: runs, shorts, review, edit, rerender, schedule (+CSV), brand, themes, AI test, connections, autopilot (OS scheduler), library, streams, export, publishing [`api`] |

Full, categorised list: **02-feature-inventory.md**.
