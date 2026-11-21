# 06 — Frontend Plan (UI/UX)

React + TypeScript SPA, served by the backend in production, Vite dev server in development. Design goals: clean, professional, no branding clutter; dark mode default; keyboard-friendly review; works at 1280px+ desktop and degrades to tablet.

## 1. Information architecture (left sidebar)

| Route | Page | Purpose |
|---|---|---|
| `/` | **Dashboard** | KPI tiles (To review · Approved · Scheduled · Published), current run progress, next autopilot run, live sessions, primary CTA ("Make Shorts" / "Review N") |
| `/create` | **Create** | New run wizard: sources (URL / upload / creators / discovery) → count & pick mode → look (style, layout, theme, brand) → preview plan (dry run) → start |
| `/runs/:id` | **Run detail** | Step timeline (download → transcribe → signals → select → render → QC), live log, candidates table, picks editor (before render), preview strips |
| `/shorts` | **Library** | Grid/list of Shorts, filters (status, run, creator, QC, date), bulk approve/reject/export |
| `/shorts/:id` | **Short studio** | Player + tabs (see §3) |
| `/review` | **Review queue** | Fullscreen one-by-one: J/K next/prev, A approve, R reject (reason), E open studio |
| `/sources` & `/sources/:id` | **Sources** | Library of analysed videos; timeline with heat graph, signals, transcript search; "make a Short from this range" |
| `/creators` | **Creators** | Watch-list, clip policy badges, live status, past streams |
| `/live` | **Live** | Sessions: status, chat-rate sparkline, spikes list with clip preview, start/stop, "export buffer" |
| `/schedule` | **Schedule** | Calendar (week/day), drag to reschedule, auto-plan, CSV export, publish preview & confirm |
| `/brand` | **Brand** | Watermark, end card, progress bar, theme editor with live caption preview, default style/layout/music |
| `/insights` | **Insights** | Channel stats, per-Short diagnosis, learned rules |
| `/settings` | **Settings** | General, AI (provider/model/effort, test, cost so far), Processing (workers, GPU, light mode, storage & retention), Integrations, Autopilot, Language, About/doctor |
| `/onboarding` | **Onboarding** | 3 steps: language → sources/creators → AI provider (auto-detected) |

## 2. Shared components

AppShell (sidebar, top bar with job indicator + disk space), JobProgress (WS-driven), VideoPlayer (range streaming, frame-step, loop region), Timeline (canvas: heat graph, signal markers, regions, playhead), WaveformRegions (wavesurfer), CaptionPreview (renders a style on a sample frame), StylePicker (grid of caption styles with previews), LayoutPicker (crop/stack/bubble/full thumbnails), QCBadge + QCDetails, StatusChip, ConfirmDialog, EmptyState, DataTable (TanStack Table), KeyboardShortcuts, Toasts, i18n LanguageSwitcher, ThemeToggle.

## 3. Short studio (editing capabilities)

| Tab | Controls |
|---|---|
| **Preview** | Player, versions dropdown (v1 render, v2 AI edit…), compare two versions side by side, QC report, cover image |
| **Trim** | Source timeline around the moment; drag in/out handles; see kept/removed speech spans; toggle filler & silence removal; for multi-part formats edit each part |
| **Captions** | Word list with times; edit text, split/merge words, mark keywords, change style/position/size; translation language |
| **Look** | Style, layout, theme, crop override (drag the 9:16 window on keyframes), zoom on peaks, flash, brightness fix |
| **Format & FX** | Format type + its fields (labels, jump card, payoff time…), meme mood + timing, music bed + level, SFX |
| **Voice** | Record in browser (MediaRecorder) or upload, set start time, ducking level |
| **Post** | Hook, title, hashtags, credit, extra aspect ratios, export/download, schedule |
| **AI edit** | Text box ("make the hook funnier and start 2 s later"), shows the parsed edit plan before applying → new version |

All edits create a **new version** via a render job; nothing overwrites the original. Edits made before rendering update the plan instantly; heavy changes trigger a background re-render with progress.

## 4. State & data flow

- TanStack Query for all server data; WebSocket messages invalidate/patch relevant queries (e.g. `short.updated` → `['short', id]`).
- Zustand for UI state (player time, selected words, review cursor).
- Typed API client generated from OpenAPI (`packages/api-client`), so backend schema changes break the build, not production.
- Forms: react-hook-form + zod schemas mirrored from backend.

## 5. UX rules

- Every long action shows progress and is cancellable; every job-starting button has a "preview plan" (dry run).
- Destructive actions confirm; publishing always requires an explicit "Confirm send" per item.
- Accessibility: Radix primitives, focus rings, ARIA labels, WCAG AA contrast, reduced-motion support.
- i18n from day one (no hard-coded strings); RTL layout for Arabic/Urdu.
- Empty states teach the next step instead of showing demos.

## 6. Frontend folder structure

```
frontend/src/
  app/ (router, providers, layout)
  pages/ (one folder per route)
  features/ (runs, shorts, studio, review, schedule, live, sources, creators, brand, settings, onboarding)
  components/ (shared UI)
  lib/ (api client wrapper, ws client, i18n, formatters, hotkeys)
  styles/ · locales/ · test/
```
