# ADR 0006 — One scene document, two renderers, a cached cut

**Status:** accepted (Phase 6b) · **Date:** 2026-11-23

## Context
Shorts get five gaming templates (Streamer First, Gameplay First, Dual Vision, Floating
Facecam, Cinematic Gaming), and after rendering, creators customise them in a studio:
logo, text, emojis, stickers, captions, effects and template parts. They expect to see
changes **instantly**, and the exported MP4 must look like what they saw. Re-rendering a
whole pick (download segment, cut pauses, analyse faces, measure loudness) for every
tweak would take far too long.

## Decision
1. **The scene is the single source of truth for the look**
   (`pipeline/render/scene.py`, a Pydantic model also exposed to the API and the
   TypeScript types). It holds the template id, the geometry (panel split, frame, floating
   cam, divider, fit), captions, effects and an ordered list of layers. Template parts
   (title, reaction caption, name tag, LIVE badge…) are ordinary layers with a `role`, so
   they can be moved, restyled or hidden like anything the user adds. Texts can use
   `{hook}`, `{title}`, `{channel}` and `{reaction}` placeholders.
2. **Two renderers, one set of rules.** FFmpeg + Pillow on the server
   (`scene_render.py`, `raster.py`), Canvas 2D in the browser (`studio/compositor.ts`,
   `draw.ts`, `track.ts`). Both use the same fonts (`GET /fonts/{id}` serves the
   renderer's own font files), the same shape geometry, the same draw order, and the same
   animation and zoom formulas. Parity is pinned by tests (tracking keyframes computed in
   Python, animation curves, caption grouping). Captions stay libass/ASS on the server
   (proven, fast); the browser imitates them.
3. **Render = cut + compose.** The *cut* (segment, pause removal, facecam/face/motion
   analysis, loudness, a 960 px editor preview with keyframes every 0.5 s) is cached per
   source + range + EDL (`services/cuts.py`, newest two per Short). The *compose* stage
   draws a scene on top of it. A studio re-render therefore only composes: ~1 s per
   second of video on CPU instead of the full pipeline.
4. **Static rasters, animated by FFmpeg.** Every text/sticker/emoji/logo layer is
   rasterised once by Pillow; animations (pop, zoom, slides, pulse, shake, float, fades)
   are FFmpeg expressions on the overlay (`scale` with `eval=frame`, padded to a fixed
   size, then `overlay` with timed `x`/`y` and `enable`). Same formulas in the canvas.
5. **Non-destructive.** Every render is a new ShortVersion that stores its full scene and
   cut key. Original footage and earlier versions are never modified. Uploaded logos are
   decoded, converted to clean PNGs (metadata stripped) and kept in a reusable library.

## Consequences
- Instant preview, fast exports, and the export matches the preview closely (verified
  side by side). Small differences can remain where the two text engines differ
  (libass vs canvas line wrapping, glitch effect approximation in the preview).
- Facecam templates need a detected facecam. Without one the scene falls back to
  Cinematic Gaming, and the studio says so.
- The cut cache costs disk space (a near-lossless intermediate). It is pruned to the newest
  two cuts per Short and removed when the source is deleted.
- Adding a template = one `default_scene` branch + one `TemplateInfo` + one icon; the
  rest of the system is template-agnostic.
