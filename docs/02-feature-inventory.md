# 02 — Feature Inventory

Every capability found in the reference (see 01), re-categorised for our product. Nothing is dropped for being hard. Priority: **P0** = MVP must-have, **P1** = v1.0, **P2** = v1.x. "Phase" refers to 09-roadmap.md.

## A. Sources & Ingestion
| # | Feature | Pri | Phase |
|---|---|---|---|
| A1 | Add source by URL: YouTube, Twitch VOD, Kick, TikTok, X, Instagram, Facebook, Rumble, Vimeo, Reddit, Dailymotion (via yt-dlp) | P0 | 2 |
| A2 | Upload / pick a local video or audio file | P0 | 2 |
| A3 | Time window on long sources (START–END); long streams default to a bounded window | P0 | 2 |
| A4 | Creator watch-list: platform + handle; enable/disable; per-creator clip policy (allowed / ask / denied / unknown + note) | P1 | 7 |
| A5 | Auto-discovery: channel RSS, keyword search lines, platform category (top VODs last 24 h) with keyword regex, language and max-duration filters | P1 | 7 |
| A6 | Skip already-used sources; never overlap already-used ranges | P0 | 4 |
| A7 | Audio-only download for analysis; segment-only download for rendering | P0 | 2 |
| A8 | Download robustness: retries, timeouts, cookie-browser option for bot/age checks, updater for yt-dlp | P1 | 2 |
| A9 | Source library: list past sources/streams per creator (Twitch/Kick/YouTube), metadata, status | P1 | 7 |

## B. Analysis & Signals
| # | Feature | Pri | Phase |
|---|---|---|---|
| B1 | Local transcription with word timestamps; GPU (CUDA) with CPU fallback; model auto-choice | P0 | 3 |
| B2 | Language detection; skip/flag other-language sources | P0 | 3 |
| B3 | Sentence segmentation with timestamps | P0 | 3 |
| B4 | Loudness spikes (dB over baseline) → `LOUD` tags | P0 | 3 |
| B5 | Chat replay ingest (Twitch, YouTube, Kick), chat-rate spikes, top phrases/emotes → `CHAT` | P1 | 3 |
| B6 | Viewer-clip hotspots (platform clips & view counts) → `CLIPPED` | P1 | 3 |
| B7 | Replay heat-map ("most replayed") → `REPLAYED` | P1 | 3 |
| B8 | Visual moment labels without AI: chase, crash, fight, stunt, reaction, funny (+laughter detection) | P1 | 3 |
| B9 | On-screen banner/event OCR (e.g. WASTED, MISSION PASSED, VICTORY, GAME OVER), wanted-level, hard cuts → `GAME` | P2 | 3 |
| B10 | Webcam/facecam box detection | P0 | 5 |
| B11 | Unified **HEAT 0–100** score per sentence | P0 | 3 |
| B12 | Timeline visualisation of signals per source (heat graph, moment markers) | P1 | 6 |

## C. Moment Selection
| # | Feature | Pri | Phase |
|---|---|---|---|
| C1 | Candidate windows: top-N ranked windows (score, tags, head…tail text) | P0 | 4 |
| C2 | Pick modes: **Smart** (AI over candidates), **Deep** (AI over full transcript), **Free** (no AI heuristic) | P0 | 4 |
| C3 | AI selection rules: premise+payoff, picture-first, game/topic filter, no spoilers/leaks, credit required, stands alone, payoff in last 40 %, story-driven length | P0 | 4 |
| C4 | Boundary snapping to sentences; min talk-time check (TOO SHORT), max span | P0 | 4 |
| C5 | Max N per batch, max 2 per source, dedupe same point | P0 | 4 |
| C6 | Callback finder (claim → payoff pairs) | P1 | 4 |
| C7 | Text generation: hook (≤6 words, caps), title (≤70 chars), 3–5 hashtags, keywords to highlight, credit | P0 | 4 |
| C8 | Preview frames (4 per pick) and AI/user drop of bad picks before render | P1 | 4 |
| C9 | Learning from own channel performance → ranking rules | P2 | 9 |
| C10 | AI provider choice + "test this AI" + show command/prompt (dry run) | P0 | 4 |

## D. Rendering & Editing
| # | Feature | Pri | Phase |
|---|---|---|---|
| D1 | Cut, 9:16 1080×1920 output, H.264/AAC, GPU encoder when present | P0 | 5 |
| D2 | Auto-reframe with shot detection + face/person tracking | P0 | 5 |
| D3 | Layouts: auto crop, **stack** (cam top / game bottom), **bubble** (round cam over game), **full** (blurred bg), video-call grid detection | P0 | 5 |
| D4 | Overlay/clutter crop, letterbox/black-bar removal | P1 | 5 |
| D5 | Dead-air trimming, filler ("um/uh") removal, tail trim | P0 | 5 |
| D6 | Zoom/punch-in on peaks, optional white flash, whoosh | P1 | 5 |
| D7 | Word-by-word captions, ~30 styles (classic, word, karaoke, box styles, glow, comic, typewriter, shake…), keyword colour, safe position (auto/top/middle/bottom, avoid faces) | P0 (5 styles) / P1 (all) | 5 |
| D8 | Hook title overlay; themes (colour/font presets) | P0 | 5 |
| D9 | Loudness normalise −14 LUFS, light noise reduction | P0 | 5 |
| D10 | Image fixes: dark-cam brightening, game gamma, black-flash/freeze cover | P1 | 5 |
| D11 | Cover/thumbnail image + post text (title, hashtags, credit) | P0 | 5 |
| D12 | Formats: moment, callback (+EARLIER tag / jump card), compilation (#3→#1), escalation, then-vs-now, reveal, chat overlay, wait-for-it (silence squeeze + bar) | P1 | 8 |
| D13 | Meme layer: moods (embarrassing, fail, shock, hype, win, awkward, cringe, funny, suspense) with SFX + visual effect, auto payoff detection, user-added sounds | P1 | 8 |
| D14 | Music bed (hype/chill/tense/funny or user file) with speech ducking | P1 | 8 |
| D15 | Voice-over: record/upload line, place at T, duck original | P1 | 8 |
| D16 | Offline translation of captions + hook (es, fr, pt, de, ar, hi, zh + more), RTL & CJK fonts | P1 | 8 |
| D17 | Branding: watermark (image/text, position incl. bounce, opacity, size), progress bar, end-card text | P1 | 8 |
| D18 | Extra aspect ratios (4:5, 1:1) | P1 | 5 |
| D19 | Versioned re-render with changed settings (style, layout, format, meme, look) | P0 | 6 |
| D20 | **Manual editor**: trim in/out on timeline, edit caption words/timing, edit hook/title, change crop keyframes | P1 | 6 |
| D21 | **AI edit**: natural-language instruction → new version (never overwrites original) | P1 | 6 |
| D22 | Overview contact sheet per batch | P1 | 5 |
| D23 | Low-resource mode (1 worker, 30 fps, duration cap) auto under 12 GB RAM | P0 | 10 |

## E. Quality Control
| # | Feature | Pri | Phase |
|---|---|---|---|
| E1 | Automatic QC per Short: duration, LUFS, black/freeze/static card frames, caption coverage, face presence, first/last frame check → PASS/WARN/FAIL + reasons | P0 | 5 |
| E2 | Auto re-cut once on FAIL with shifted boundary; drop if still failing | P1 | 5 |

## F. Review, Library & Scheduling
| # | Feature | Pri | Phase |
|---|---|---|---|
| F1 | Dashboard: counts to review / approved / scheduled / published, progress of current run, primary CTA | P0 | 6 |
| F2 | Shorts library across runs: player, metadata, QC badge, versions, filters | P0 | 6 |
| F3 | Review: approve / reject (with reason), bulk actions | P0 | 6 |
| F4 | Schedule calendar (local time + UTC), bulk plan ("spread across the day"), CSV export | P1 | 9 |
| F5 | Export: download MP4 + cover + text, ZIP of a run | P0 | 6 |
| F6 | Reveal file in OS explorer; disk-space indicator | P1 | 6 |

## G. Publishing & Integrations
| # | Feature | Pri | Phase |
|---|---|---|---|
| G1 | Publishing connector interface; first connector = direct YouTube Data API upload (own OAuth). Third-party schedulers as optional connectors | P1 | 9 |
| G2 | Preview + explicit "Confirm send" per Short; never auto-post without approval | P0 | 9 |
| G3 | Connection test per integration; secrets stored encrypted | P1 | 9 |
| G4 | YouTube performance stats (Data API key + optional OAuth Analytics) and AI diagnosis/ideas | P2 | 9 |

## H. Live
| # | Feature | Pri | Phase |
|---|---|---|---|
| H1 | Record a live stream (Twitch, Kick, YouTube) into a rolling buffer (last ~10 min) | P1 | 7 |
| H2 | Anonymous chat reader; rate baseline; spike (ratio/min thresholds) → cut −25 s/+10 s, transcribe, enqueue as candidate | P1 | 7 |
| H3 | "Live hunt": check which watched creators are live, start/stop sessions, show chat rate & clips found | P1 | 7 |
| H4 | Buffer export for word-based picking | P1 | 7 |

## I. Automation
| # | Feature | Pri | Phase |
|---|---|---|---|
| I1 | Autopilot: scheduled runs (days + time) with dry-run preview; implemented by our own scheduler (not OS cron) | P1 | 9 |
| I2 | Run presets (N Shorts, pick mode, style, sources) | P1 | 9 |

## J. App, Settings & Onboarding
| # | Feature | Pri | Phase |
|---|---|---|---|
| J1 | Onboarding (3 steps): language, creators/sources, AI provider (auto-detect what's available) | P0 | 6 |
| J2 | i18n UI: en, es, fr, pt, de, ar (RTL), it, tr, zh (+ ur/hi easy to add) | P1 | 6 |
| J3 | Settings: AI provider & keys, pick mode, live mode, workers, GPU, storage paths, defaults | P0 | 6 |
| J4 | Brand profile page | P1 | 8 |
| J5 | Theme (light/dark) | P0 | 6 |
| J6 | Help / in-app hints mapping common errors to fixes | P1 | 10 |
| J7 | Optional login for server deployments (single-user local mode has none) | P1 | 11 |
