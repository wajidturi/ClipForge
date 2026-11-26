# Gaming templates & the customisation studio (Phase 6b)

Workflow: **Upload clips → choose a template → generate → review → customise → export**,
all inside the app. Design: [ADR 0006](../adr/0006-scene-rendering-and-studio.md).

## The five templates

| Template | Layout | Default elements | Default effects | Studio controls |
|---|---|---|---|---|
| **Streamer First** | facecam panel on top (42%), gameplay below, neon frames | LIVE badge, reaction burst on the cam (`{reaction}`, shakes), streamer name pill, big slanted yellow title (`{hook}`) | zoom punch, flash | facecam height, frame |
| **Gameplay First** | gameplay on top (62%), facecam below | 💀 kill banner burst (`{hook}`), score highlight `+100` (hidden), reaction ribbon on the cam, name pill | zoom punch, shake | gameplay height, frame |
| **Dual Vision** | 50/50 with a tilted gradient divider | 🎮 divider label (`{hook}`), reaction burst, name pill | zoom punch, flash | split, divider style/colours/thickness/tilt, frame |
| **Floating Facecam** | full-screen gameplay + round facecam bubble with glowing ring | big slanted title, name tag, pulsing SUBSCRIBE 🔔 in the last 4 s, reaction (hidden) | zoom punch | bubble size/position (drag on the preview), shape, border, glow, fit |
| **Cinematic Gaming** | full screen | 💀 title burst, giant impact word on the second peak (`{reaction}`, zooms in and shakes), name pill | stronger zoom, shake, flash, glitch, speed lines, vignette, cinematic grade | fit, every effect |

The chosen template is always used. Each one has its own caption look (Gaming, Box,
One word, Karaoke, Classic); switching template takes the new look unless you changed
the captions yourself. `Automatic` picks Streamer First when facecams are found,
otherwise Cinematic Gaming.

### People and facecams (`reframe.find_people`)

MediaPipe's detector only sees faces that fill a good part of the image, so frames are
also scanned in overlapping 480 px tiles (frame scaled to 1920 wide) to find the small
(~100 px) faces inside facecam overlays: the whole frame once a second, and in between
only a tile around each small face found. Faces are linked across samples by
position, and each person gets a mouth-movement score (lip gap / face height) that says
who is talking.

| Found | Facecam panel shows | Crop of the main footage |
|---|---|---|
| **overlay**: steady, tiny (< 2.5% of the frame), off-centre faces | one tile per cam overlay, side by side (up to 3); people sharing one cam stay in one tile; the floating bubble shows whoever talks most | follows the action with every cam masked out |
| **camera**: people filmed by the main camera (IRL, couch streams) | one tile per person | keeps the group in the shot when it fits 9:16, else follows whoever is talking (switches only when someone clearly talks more) |
| nobody | a close-up of where the action mostly is (with a note) | follows the action |

When the cams have their own panel, the overlays are blurred inside the gameplay so a
crop that reaches a corner does not show a cut-off second copy of the streamer. A narrow
facecam tile zooms in on the face (the crop grows at most 1.3× past the cam box) instead
of pulling in what sits above or below the cam.

`{reaction}` is a short exclamation the streamer actually said near the peak ("OH MY GOD!",
"NO WAY!", "LET'S GO!"…), found in the transcript, else "NO WAY!".

## Studio (`/shorts/:id`, tab "Customise", opens by default)

- **Live preview** on a canvas over the cut's preview video, with play/scrub, mute, and a
  switch to the **rendered video** of the active version.
- **Direct manipulation:** click to select, drag to move, round corner handle to resize
  (also for the floating facecam), arrows to nudge, Delete to remove.
- **Undo/redo** (Ctrl+Z, Ctrl+Shift+Z / Ctrl+Y); a drag or slider move is one step.
  "Discard changes" goes back to the rendered version; "Template defaults" restores
  the template's own elements and keeps your logo and text.
- **Panels:** Template (template-aware geometry + quick text/visibility for its elements),
  Elements (all layers, show/hide), Add (text, logo upload and image library, 14 gaming
  stickers, emojis), Captions (presets, font, size, colours, highlight, outline, box,
  words at once, position, pop-in), Effects (zoom punch strength, shake, flash, glitch,
  speed lines, vignette, cinema bars, colour grade, effect moments at the playhead).
- **Inspector** for the selected element: text with placeholders, font, size, colours,
  outline, letters (CAPS/italic), shadow, background shape (box, pill, tag, ribbon,
  comic burst) and colours, max width, position, scale/width, rotation, opacity, timing
  (from/until, "start here", "end here", whole video), entrance/loop/exit animation.
- **Render final video** creates a new version (origin `manual_edit`). While it renders
  you can keep editing; nothing is overwritten.

Other studio tabs stay: Post (title/hashtags), Trim, Caption words (spelling fixes),
AI edit (its `set_layout` now switches templates).

## One-click flow

- **Create** → choose sources → pick mode (Smart, Deep, No AI, or **Whole clip**: an uploaded
  short clip becomes one Short) → "Generate the videos right away" + template → the run
  renders every pick. Settings → "Render picks automatically" and "Default template"
  apply too.
- **Run page:** template cards for rendering the remaining picks. Rendered picks show
  **Review & customise** (downloads are in the studio, after review).

## API

| Method & path | Purpose |
|---|---|
| `GET /render/options` | templates, caption presets, fonts, sizes, encoder |
| `POST /shorts/{id}/render` | `template` and/or a full `scene` (plus `origin`, `aspects`, `caption_overrides`) |
| `POST /runs` | `pick_mode: "whole"`, `render: {template, aspects}` |
| `GET /shorts/{id}/studio` | active scene, placeholder values, caption fixes, cut data for the live preview |
| `POST /shorts/{id}/scene/template` | another template's defaults, keeping user layers |
| `GET /fonts/{id}` | font files shared with the renderer |
| `GET/POST /images`, `DELETE /images/{id}` | logo/image library (PNG, JPG, WebP, GIF ≤ 10 MB) |

## Performance (this PC, x264)

18 s clip: first render (cut + compose) 25 s; studio re-render (compose only) 19 s,
including the cover and QC. Cinematic with shake costs ~2× compose time (the shake
re-scales the full frame).

## Tests

Backend `tests/test_templates.py`: template defaults and geometry for all five, facecam
fallback, template switching, placeholders/validation, cover crop, reaction finding,
tracking refactor, rasterising (emoji runs, shapes, frame holes, cam ring), image
library, fonts, a real render → studio → customised re-render reusing the cut,
one-click runs, whole-clip picks, source deletion cleanup. Frontend
`features/studio/studio.test.tsx`: tracking parity with Python, zoom/animation curves,
caption grouping, undo/redo, and the studio UI (add a sticker, undo/redo, effects,
render sends the scene).

## Not done yet

- Facecam analysis costs ~0.45 s per second of clip (the tile scan).
- Custom sticker images (beyond logos), sound effects, per-word caption animation styles,
  a timeline track view, and keyframed motion are natural next steps.
- The glitch effect is approximated in the preview.
