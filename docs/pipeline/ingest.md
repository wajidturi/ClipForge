# Pipeline: Ingestion (Phase 2)

Turns a link or a file into a **source** with analysable audio on disk. Later phases (transcription, signals, rendering) only read what this step stores.

## Flow

```mermaid
flowchart TD
  A[POST /api/v1/sources  or  /sources/upload] --> R{resolve}
  R -- link --> V[resolver: platform + id, reject LAN/playlists/channels]
  R -- file --> U[stream to disk, sha256, size limit, extension check]
  V & U --> D{already in library?}
  D -- yes --> X[return existing source, 200]
  D -- no --> J[enqueue job source.ingest  subject=source]
  J --> W[worker]
  W -- link --> M[yt-dlp metadata] --> L{live? too long?} --> WIN[window] --> DA[audio-only download of the window] --> CHK[alignment check]
  W -- file --> P[ffprobe: has audio?] --> WIN2[window] --> EA[ffmpeg audio extract]
  CHK & EA --> AS[MediaAssets: audio (+ original video)] --> OK[status ready]
```

| Module | Role |
|---|---|
| `pipeline/ingest/resolver.py` | Offline link check: 11 platforms, video id, normalised URL; rejects non-http, localhost/LAN/single-label hosts, playlists and channel pages |
| `pipeline/ingest/timewin.py` | `90`, `1:30`, `1:02:03` parsing; windows (min 10 s); default window for over-long videos |
| `pipeline/ingest/downloader.py` | yt-dlp wrapper (injectable for tests): metadata → `RemoteInfo`, audio download, exact range download for segments; cancel via progress hook |
| `pipeline/ingest/errors.py` | Raw yt-dlp/ffmpeg errors → short message + fix + retryable flag |
| `core/ffmpeg.py` | ffprobe, ffmpeg runner with progress and cancel (kills the process), audio extract, segment cut |
| `services/sources.py` | Create (link/upload, dedupe), retry, delete (cancels jobs, removes files) |
| `services/ingest.py` | The `source.ingest` job |
| `services/segments.py` | `ensure_segment(source, start, end)`: cached mp4 of a range, used by rendering (Phase 5) |

## Rules

- **Duplicates:** the same video added twice (any link form, e.g. `youtu.be/ID` and `watch?v=ID`) returns the existing source. Uploads are deduplicated by SHA-256 of the file. A failed source added again is retried.
- **Live streams** are refused here (they belong to Live clipping, Phase 7).
- **Long videos:** up to `CF_MAX_SOURCE_HOURS` (12 h) are used whole. Longer ones without a window → the last `CF_DEFAULT_WINDOW_HOURS` (2 h) are used and the source shows a note.
- **Download speed:** a whole video downloads over parallel, resumable connections; streams slower than 100 KB/s are treated as throttled and re-fetched. Parts of a video up to 30 min are fetched as a section (ffmpeg); longer parts are downloaded whole and cut locally (exact, much faster).
- **Times are always full-video times.** A source ingested with window 1:00:00–1:30:00 keeps `window_start_s=3600`; later steps add it to audio-relative times.
- **Retries:** network/rate-limit errors retry (3 attempts, backoff); bad input (private, removed, unsupported, no audio) fails at once with a hint.

## Exact windows (important)

yt-dlp cuts ranges with FFmpeg stream copy, which can only start at a keyframe/cluster. For audio-only WebM this silently started **at 0 s instead of 5 s** in our real-network test, which would have shifted every transcript timestamp. Fixes:

1. `force_keyframes_at_cuts=True` for windowed audio (re-encodes at the cut). Verified by cross-correlating the cut with the full audio: starts at 4.999 s for a 5 s window.
2. `check_window_alignment()` fails the job if a windowed download is longer than its window (+1.5 s), so a future yt-dlp change cannot reintroduce the bug silently.

## Settings

| Env var | Default | Meaning |
|---|---|---|
| `CF_YTDLP_COOKIES_BROWSER` | – | e.g. `firefox`: borrow that browser's cookies when a site asks for sign-in/bot check |
| `CF_YTDLP_RETRIES` | 5 | network retries inside yt-dlp |
| `CF_YTDLP_SOCKET_TIMEOUT` | 30 | seconds |
| `CF_MAX_SOURCE_HOURS` | 12 | longer sources get a default window |
| `CF_DEFAULT_WINDOW_HOURS` | 2 | size of that window (from the end) |
| `CF_MAX_UPLOAD_MB` | 60000 | upload limit (a 10 h 1080p recording) |

`clipforge update-downloader` updates yt-dlp (sites change often).

## API

| Method | Path | |
|---|---|---|
| POST | `/api/v1/sources` | `{url, start?, end?}` → 201 new / 200 existing |
| POST | `/api/v1/sources/upload` | multipart `file`, `start?`, `end?` |
| GET | `/api/v1/sources` | `status`, `platform`, `q`, `limit`, `cursor` |
| GET | `/api/v1/sources/{id}` | + assets, chapters, `has_heatmap` |
| POST | `/api/v1/sources/{id}/retry` | |
| DELETE | `/api/v1/sources/{id}` | cancels jobs, deletes files |
| GET | `/api/v1/sources/platforms` | supported sites |
| GET | `/api/v1/media/{asset_id}` | file with HTTP range support |

WebSocket events: `source.updated`, `source.deleted` (plus `job.updated` for progress).

## Tests

- Unit: 21 links across all 11 platforms, rejections, time parsing, error hints, yt-dlp options/progress/cancel with a fake YoutubeDL.
- Flow (real FFmpeg media, fake downloader for links): upload → worker → assets; windows; dedupe; bad/silent files; live refusal; private vs rate-limit retry; delete; search; WebSocket; segments; alignment guard.
- Network (manual, `CF_TEST_NETWORK=1 uv run pytest -m network`): real YouTube metadata, exact 7 s audio window, 6 s video segment.
