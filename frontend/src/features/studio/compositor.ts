/**
 * Live preview: draws a scene on a canvas from the cut's preview video, in the same
 * order and with the same animation formulas as backend `scene_render.py`:
 * panels -> zoom -> colour -> frame -> speed lines -> captions -> layers ->
 * shake -> flash -> glitch. Layer and frame graphics are rasterised once and cached.
 */
import type { Captions, Cut, Layer, Scene } from '@/lib/api/client'
import {
  H,
  W,
  coverCrop,
  even,
  family,
  frameCanvas,
  panels,
  camList,
  camTiles,
  CAM_MAX_GROW,
  hideRects,
  matteCrop,
  renderImageLayer,
  renderTextLayer,
  speedLines,
  type Rect,
} from './draw'
import { trackTargets, xAt, zoomAt, type Key } from './track'

export type Model = {
  scene: Scene
  cut: Cut
  values: Record<string, string | null | undefined>
  overrides: Record<string, string>
  keywords: string[]
}

export type Bounds = { id: string; x: number; y: number; w: number; h: number }

const ALPHA_IN: Record<string, number> = { pop: 0.12, zoom: 0.2, fade: 0.3, none: 0 }
const SLIDE: Record<string, [number, number]> = {
  slide_up: [0, 220],
  slide_down: [0, -220],
  slide_left: [700, 0],
  slide_right: [-700, 0],
}
const clip = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v))

export function fillText(text: string, values: Model['values']): string {
  return text
    .replace(/\{(hook|title|channel|reaction)\}/g, (_, k: string) => (values[k] ?? '').trim())
    .trim()
}

/** Scale, alpha and offset of a layer at time t (backend _scale_expr/_offset_exprs). */
export function layerAnim(ly: Layer, t: number, duration: number) {
  const end = ly.end != null ? Math.min(duration, ly.end) : duration
  const u = Math.max(0, t - ly.start)
  let s = 1
  if (ly.anim_in === 'pop')
    s = u < 0.22 ? 0.3 + (0.85 * u) / 0.22 : u < 0.37 ? 1.15 - (0.15 * (u - 0.22)) / 0.15 : 1
  else if (ly.anim_in === 'zoom') s = u < 0.3 ? 1.8 - (0.8 * u) / 0.3 : 1
  if (ly.loop === 'pulse') s *= 1 + 0.06 * Math.sin(2 * Math.PI * 1.6 * u)
  const aIn = ALPHA_IN[ly.anim_in] ?? 0.2
  let alpha = aIn > 0 ? clip(u / aIn) : 1
  if (ly.anim_out === 'fade' && ly.end != null && end - ly.start > 0.4)
    alpha *= clip((end - t) / 0.25)
  let dx = 0
  let dy = 0
  const sl = SLIDE[ly.anim_in]
  if (sl) {
    const e = 1 - (1 - clip(u / 0.35)) ** 3
    dx += sl[0] * (1 - e)
    dy += sl[1] * (1 - e)
  }
  if (ly.loop === 'shake') {
    dx += 6 * Math.sin(2 * Math.PI * 9 * u)
    dy += 4 * Math.sin(2 * Math.PI * 13 * u + 1)
  } else if (ly.loop === 'float') dy += 10 * Math.sin(2 * Math.PI * 0.8 * u)
  const visible = ly.visible && t >= ly.start && t < end && end - ly.start >= 0.05
  return { s, alpha, dx, dy, visible }
}

// ------------------------------------------------------------------ captions
type Word = { start: number; end: number; text: string }
type Group = { words: Word[]; start: number; end: number }

export function groupWords(words: Word[], size: number, maxGap = 0.6): Group[] {
  const groups: Word[][] = []
  for (const w of words) {
    const cur = groups[groups.length - 1]
    if (
      !cur ||
      cur.length >= size ||
      w.start - cur[cur.length - 1]!.end > maxGap ||
      /[.?!]$/.test(cur[cur.length - 1]!.text.trimEnd())
    )
      groups.push([w])
    else cur.push(w)
  }
  return groups.map((g, i) => {
    const nxt = i + 1 < groups.length ? groups[i + 1]![0]!.start : g[g.length - 1]!.end + 0.6
    return { words: g, start: g[0]!.start, end: Math.min(nxt, g[g.length - 1]!.end + 0.6) }
  })
}

const norm = (w: string) => w.replace(/[^\p{L}\p{N}']/gu, '').toUpperCase()

function drawCaptions(
  ctx: CanvasRenderingContext2D,
  c: Captions,
  groups: Group[],
  kw: Set<string>,
  t: number,
) {
  const g = groups.find((x) => t >= x.start && t < x.end)
  if (!g) return
  const word = (w: Word) => (c.upper ? w.text.trim().toUpperCase() : w.text.trim())
  let parts: { text: string; color: string }[]
  let pop = c.animation === 'pop' ? 1.14 - 0.14 * clip((t - g.start) / 0.11) : 1
  const colourOf = (w: Word) => (kw.has(norm(w.text)) ? c.keyword : c.color)
  if (c.mode === 'single') {
    const i = g.words.findIndex((w, k) => t >= w.start && t < (g.words[k + 1]?.start ?? g.end))
    const w = g.words[Math.max(0, i)]!
    parts = [{ text: word(w), color: colourOf(w) }]
    pop = 1.18 - 0.18 * clip((t - w.start) / 0.09)
  } else {
    parts = g.words.map((w, i) => {
      const next = g.words[i + 1]?.start ?? g.end
      const from = i === 0 ? g.start : w.start
      let color = colourOf(w)
      if (c.mode === 'highlight' && t >= from && t < next) color = c.highlight
      if (c.mode === 'karaoke' && t >= w.start)
        color = kw.has(norm(w.text)) ? c.keyword : c.highlight
      return { text: word(w), color }
    })
  }
  ctx.save()
  ctx.font = `${c.size}px "${family(c.font)}"`
  ctx.textBaseline = 'middle'
  const space = ctx.measureText(' ').width
  const widths = parts.map((p) => ctx.measureText(p.text).width)
  // wrap like libass (80 px side margins): two balanced lines when too wide
  const total = widths.reduce((a, b) => a + b, 0) + space * (parts.length - 1)
  const lines: number[][] = []
  if (total > W - 160 && parts.length > 1) {
    let acc = 0
    let cut = parts.length - 1
    for (let i = 0; i < parts.length; i++) {
      acc += widths[i]! + space
      if (acc >= total / 2) {
        cut = Math.max(1, i + 1)
        break
      }
    }
    lines.push([...parts.keys()].slice(0, cut), [...parts.keys()].slice(cut))
  } else lines.push([...parts.keys()])
  const lh = c.size * 1.15
  const cy = c.y * H
  ctx.translate(W / 2, cy)
  ctx.scale(pop, pop)
  lines.forEach((idx, li) => {
    const lw = idx.reduce((a, i) => a + widths[i]!, 0) + space * (idx.length - 1)
    const y = (li - (lines.length - 1)) * lh
    if (c.box) {
      ctx.fillStyle = c.box
      ctx.fillRect(
        -lw / 2 - c.outline,
        y - c.size * 0.6 - c.outline,
        lw + 2 * c.outline,
        c.size * 1.2 + 2 * c.outline,
      )
    }
    let x = -lw / 2
    for (const i of idx) {
      const p = parts[i]!
      if (!c.box && c.outline > 0) {
        ctx.lineJoin = 'round'
        ctx.lineWidth = c.outline * 2
        ctx.strokeStyle = c.outline_color
        ctx.strokeText(p.text, x, y)
      }
      ctx.fillStyle = p.color
      ctx.fillText(p.text, x, y)
      x += widths[i]! + space
    }
  })
  ctx.restore()
}

// ------------------------------------------------------------------ compositor
/** Approximations of scene_render.HDR and cam_look (canvas filters cannot sharpen). */
const HDR_FILTER = 'saturate(1.3) contrast(1.1) brightness(1.02)'
const CAM_ENHANCE = 'contrast(1.06) saturate(1.08)'
const BLUR_BACKGROUNDS: Record<string, number> = { blur_soft: 10, blur_strong: 26 } // scene.py

type Cached = { key: string; img: HTMLCanvasElement }

export class Compositor {
  private ctx: CanvasRenderingContext2D | null
  private model: Model | null = null
  private frame: Cached | null = null
  private layers = new Map<string, Cached>()
  private keys = new Map<string, Key[]>()
  private groups: Group[] = []
  private kw = new Set<string>()
  bounds: Bounds[] = []
  private canvas: HTMLCanvasElement
  private video: HTMLVideoElement
  private images: Map<string, HTMLImageElement>
  private resolution: number
  private matte: HTMLVideoElement | null = null
  private bgs = new Map<string, HTMLImageElement>()
  private scratches: HTMLCanvasElement[] = []

  constructor(
    canvas: HTMLCanvasElement,
    video: HTMLVideoElement,
    images: Map<string, HTMLImageElement>,
    resolution = 0.5,
  ) {
    this.canvas = canvas
    this.video = video
    this.images = images
    this.resolution = resolution
    canvas.width = Math.round(W * resolution)
    canvas.height = Math.round(H * resolution)
    this.ctx = canvas.getContext('2d') // null in test environments without canvas
  }

  setModel(m: Model) {
    const prev = this.model
    this.model = m
    if (!prev || prev.cut !== m.cut || prev.overrides !== m.overrides) {
      const words = m.cut.words
        .map(([start, end, text, key]) => {
          const fix = m.overrides[key]
          return fix === undefined
            ? { start, end, text }
            : fix.trim()
              ? { start, end, text: fix.trim() }
              : null
        })
        .filter((w): w is Word => w !== null)
      this.groups = groupWords(words, m.scene.captions.words)
    }
    if (prev && prev.scene.captions.words !== m.scene.captions.words) {
      this.groups = groupWords(
        this.groups.flatMap((g) => g.words),
        m.scene.captions.words,
      )
    }
    this.kw = new Set(m.keywords.map(norm).filter(Boolean))
  }

  /** The person cut-out video (cut.matte_asset_id); kept in step with the preview. */
  setMatte(el: HTMLVideoElement | null) {
    this.matte = el
  }

  /** Called when a background picture finished loading (redraw). */
  onAsset: (() => void) | null = null

  private background(id: string, w: number, h: number): HTMLImageElement | null {
    const key = `${id}_${w}x${h}`
    let img = this.bgs.get(key)
    if (!img) {
      img = new Image()
      img.onload = () => this.onAsset?.()
      img.src = `/api/v1/render/backgrounds/${id}.png?w=${w}&h=${h}`
      this.bgs.set(key, img)
    }
    return img.complete && img.naturalWidth ? img : null
  }

  private syncMatte(t: number) {
    const m = this.matte
    if (!m || m.readyState < 1) return
    if (this.video.paused) {
      if (!m.paused) m.pause()
      if (Math.abs(m.currentTime - t) > 0.02) m.currentTime = t
    } else {
      if (m.paused) void m.play().catch(() => undefined)
      if (Math.abs(m.currentTime - t) > 0.15) m.currentTime = t
    }
  }

  /** Like the renderer's alphamerge: the streamer from the cam crop, with the matte as
   *  alpha, on a tile-sized canvas. Null when there is nothing to cut out. */
  private cutOut(
    scene: Scene,
    cut: Cut,
    rect: [number, number, number, number],
    r: Rect,
    f: number,
    look: string,
  ): HTMLCanvasElement | null {
    const m = this.matte
    const ok =
      scene.regions.cam_bg !== 'original' &&
      !!cut.matte_asset_id &&
      (cut.cam_kind === 'overlay' || cut.cam_kind === 'camera') &&
      !!m &&
      m.readyState >= 2
    if (!ok || !m) return null
    const w = Math.max(2, Math.round(r.w * this.resolution))
    const h = Math.max(2, Math.round(r.h * this.resolution))
    const pc = this.scratch(0, w, h)
    const mc = this.scratch(1, w, h)
    const pctx = pc.getContext('2d', { willReadFrequently: true })
    const mctx = mc.getContext('2d', { willReadFrequently: true })
    if (!pctx || !mctx) return null
    const [x, y, cw, ch] = rect
    pctx.filter = look || 'none'
    pctx.drawImage(this.video, x * f, y * f, cw * f, ch * f, 0, 0, w, h)
    const mw = cut.matte_w || m.videoWidth
    const mh = cut.matte_h || m.videoHeight
    if (!mw || !mh) return null
    const [qx, qy, qw, qh] = matteCrop(rect, cut.src_w, cut.src_h, mw, mh)
    const k = (m.videoWidth || mw) / mw
    mctx.drawImage(m, qx * k, qy * k, qw * k, qh * k, 0, 0, w, h)
    const pd = pctx.getImageData(0, 0, w, h)
    const md = mctx.getImageData(0, 0, w, h).data
    for (let i = 3; i < pd.data.length; i += 4) pd.data[i] = md[i - 3]!
    pctx.putImageData(pd, 0, 0)
    return pc
  }

  private scratch(i: number, w: number, h: number): HTMLCanvasElement {
    let c = this.scratches[i]
    if (!c) {
      c = document.createElement('canvas')
      this.scratches[i] = c
    }
    if (c.width !== w || c.height !== h) {
      c.width = w
      c.height = h
    }
    return c
  }

  /** Like scene_render.hide_cams: blur the facecam overlays inside the gameplay when
   *  the cams have their own panel. `at` maps source px to canvas px. */
  private hideCams(
    scene: Scene,
    cut: Cut,
    at: (sx: number, sy: number) => [number, number],
    kx: number,
    ky: number,
    filter: string,
  ) {
    const ctx = this.ctx
    if (!ctx || cut.cam_kind !== 'overlay' || !panels(scene).cam) return
    const v = this.video
    const f = (v.videoWidth || cut.src_w) / cut.src_w
    const cams = cut.cams?.length ? cut.cams : cut.cam ? [cut.cam] : []
    for (const [x, y, w, h] of hideRects(cams, cut.src_w, cut.src_h) as [
      number,
      number,
      number,
      number,
    ][]) {
      const [dx, dy] = at(x, y)
      const r = Math.max(2, Math.min(20, Math.floor(w / 8), Math.floor(h / 8))) * kx
      ctx.save()
      ctx.beginPath()
      ctx.rect(dx, dy, w * kx, h * ky)
      ctx.clip()
      ctx.filter = `${filter === 'none' ? '' : filter} blur(${r.toFixed(1)}px) brightness(0.92)`
      ctx.drawImage(v, x * f, y * f, w * f, h * f, dx, dy, w * kx, h * ky)
      ctx.restore()
    }
  }

  private gameKeys(rect: Rect, cw: number): Key[] {
    const m = this.model!
    const k = `${rect.w}x${rect.h}:${cw}`
    let keys = this.keys.get(k)
    if (!keys) {
      keys = trackTargets(
        m.cut.targets as [number, number | null][],
        m.cut.cuts,
        Math.min(1, cw / m.cut.src_w),
      )
      this.keys.set(k, keys)
    }
    return keys
  }

  private frameImage(scene: Scene) {
    const key = JSON.stringify([
      scene.template,
      scene.regions,
      scene.effects.letterbox,
      scene.effects.vignette,
    ])
    if (this.frame?.key !== key)
      this.frame = { key, img: frameCanvas(scene) ?? document.createElement('canvas') }
    return this.frame.img.width > 1 ? this.frame.img : null
  }

  private layerImage(ly: Layer): HTMLCanvasElement | null {
    const m = this.model!
    if (ly.kind === 'image') {
      const img = ly.asset_id ? this.images.get(ly.asset_id) : undefined
      if (!img?.complete || !img.naturalWidth) return null
      const key = JSON.stringify([ly.width, ly.scale, ly.rotation, ly.opacity, ly.asset_id])
      const c = this.layers.get(ly.id)
      if (c?.key === key) return c.img
      const out = renderImageLayer(ly, img)
      this.layers.set(ly.id, { key, img: out })
      return out
    }
    const text = fillText(ly.text, m.values)
    if (!text) return null
    const key = JSON.stringify([ly, text])
    const c = this.layers.get(ly.id)
    if (c?.key === key) return c.img
    const out = renderTextLayer(ly, text)
    this.layers.set(ly.id, { key, img: out })
    return out
  }

  /** Forget cached rasters (e.g. after fonts finish loading). */
  invalidate() {
    this.layers.clear()
    this.frame = null
  }

  draw(t: number) {
    const m = this.model
    if (!m) return
    const { scene, cut } = m
    const ctx = this.ctx
    if (!ctx) return
    const v = this.video
    const fx = scene.effects
    const d = cut.duration
    const moments = fx.moments.filter((x) => x >= 0 && x < d)
    const decay = (len: number) =>
      moments.reduce((a, x) => a + (t >= x && t <= x + len ? 1 - (t - x) / len : 0), 0)
    const within = (len: number) => moments.some((x) => t >= x && t <= x + len)

    ctx.setTransform(this.resolution, 0, 0, this.resolution, 0, 0)
    ctx.clearRect(0, 0, W, H)
    if (fx.shake && moments.length) {
      const k = decay(0.35)
      const ox = 24 + 18 * Math.sin(75 * t) * k
      const oy = 24 + 14 * Math.sin(61 * t + 1) * k
      ctx.scale(W / (W - 48), H / (H - 48))
      ctx.translate(-ox, -oy)
    }
    ctx.fillStyle = scene.regions.frame.background
    ctx.fillRect(0, 0, W, H)

    this.syncMatte(t)
    const p = panels(scene)
    const vw = v.videoWidth || cut.src_w
    const f = vw / cut.src_w // preview video is smaller than the source
    const filter =
      fx.color === 'hdr'
        ? HDR_FILTER
        : fx.color === 'vivid'
          ? 'saturate(1.22) contrast(1.05)'
          : fx.color === 'cinematic'
            ? 'saturate(1.1) contrast(1.12) brightness(0.98)'
            : 'none'
    const ready = v.readyState >= 2
    const fit = ['floating_facecam', 'cinematic'].includes(scene.template)
      ? scene.regions.fit
      : 'fill'
    if (ready) {
      const g = p.game!
      ctx.save()
      ctx.beginPath()
      ctx.rect(g.x, g.y, g.w, g.h)
      ctx.clip()
      ctx.filter = filter
      const z = fx.zoom_punch ? zoomAt(cut.zoom_peaks, t, fx.zoom_amount) : 1
      // zoom around the panel centre (server: scale the panel, crop the middle)
      ctx.translate(g.x + g.w / 2, g.y + g.h / 2)
      ctx.scale(z, z)
      ctx.translate(-(g.x + g.w / 2), -(g.y + g.h / 2))
      if (fit === 'blur') {
        const sc = Math.max(g.w / cut.src_w, g.h / cut.src_h)
        ctx.filter = `${filter === 'none' ? '' : filter} blur(12px) brightness(0.86)`
        ctx.drawImage(
          v,
          g.x + (g.w - cut.src_w * sc) / 2,
          g.y + (g.h - cut.src_h * sc) / 2,
          cut.src_w * sc,
          cut.src_h * sc,
        )
        ctx.filter = filter
        const fs = Math.min(g.w / cut.src_w, g.h / cut.src_h)
        const ox = g.x + (g.w - cut.src_w * fs) / 2
        const oy = g.y + (g.h - cut.src_h * fs) / 2
        ctx.drawImage(v, ox, oy, cut.src_w * fs, cut.src_h * fs)
        this.hideCams(scene, cut, (sx, sy) => [ox + sx * fs, oy + sy * fs], fs, fs, filter)
      } else {
        const ar = g.w / g.h
        let ch = cut.src_h
        let cw = even(ch * ar)
        if (cw > cut.src_w) {
          cw = even(cut.src_w)
          ch = even(cw / ar)
        }
        const x = xAt(this.gameKeys(g, cw), t) * cut.src_w
        const y = Math.floor((cut.src_h - ch) / 2)
        ctx.drawImage(v, x * f, y * f, cw * f, ch * f, g.x, g.y, g.w, g.h)
        const kx = g.w / cw
        const ky = g.h / ch
        this.hideCams(
          scene,
          cut,
          (sx, sy) => [g.x + (sx - x) * kx, g.y + (sy - y) * ky],
          kx,
          ky,
          filter,
        )
      }
      ctx.restore()
      const cams = p.cam ? camList(cut, scene.template) : []
      const tiles = p.cam ? camTiles(p.cam, cams.length) : []
      cams.forEach((cam, i) => {
        const r = tiles[i]!
        const rect = coverCrop(cam, r.w / r.h, cut.src_w, cut.src_h, CAM_MAX_GROW)
        const [x, y, cw, ch] = rect
        ctx.save()
        ctx.filter = filter
        if (scene.template === 'floating_facecam') {
          ctx.beginPath()
          const shape = scene.regions.cam.shape
          if (shape === 'circle')
            ctx.ellipse(r.x + r.w / 2, r.y + r.h / 2, r.w / 2, r.h / 2, 0, 0, Math.PI * 2)
          else ctx.roundRect(r.x, r.y, r.w, r.h, shape === 'rounded' ? r.w * 0.22 : 0)
          ctx.clip()
        }
        const look = scene.regions.cam_enhance ? CAM_ENHANCE : ''
        const person = this.cutOut(scene, cut, rect, r, f, look)
        if (person) {
          const bg = scene.regions.cam_bg
          const blur = BLUR_BACKGROUNDS[bg]
          if (blur) {
            const px = Math.max(2, Math.min((blur * r.w) / W, r.w / 8, r.h / 8))
            const soft = (px * 0.6 * this.resolution).toFixed(1)
            ctx.filter = `${filter === 'none' ? '' : filter} blur(${soft}px) brightness(0.97)`
            ctx.drawImage(v, x * f, y * f, cw * f, ch * f, r.x, r.y, r.w, r.h)
          } else {
            const img = this.background(bg, r.w, r.h)
            if (img) ctx.drawImage(img, r.x, r.y, r.w, r.h)
          }
          ctx.filter = filter
          ctx.drawImage(person, r.x, r.y, r.w, r.h)
        } else {
          ctx.filter = [filter === 'none' ? '' : filter, look].join(' ').trim() || 'none'
          ctx.drawImage(v, x * f, y * f, cw * f, ch * f, r.x, r.y, r.w, r.h)
        }
        ctx.restore()
      })
    }

    const frame = this.frameImage(scene)
    if (frame) ctx.drawImage(frame, 0, 0)
    if (fx.speed_lines && within(0.45)) ctx.drawImage(speedLines(), 0, 0)
    if (scene.captions.visible) drawCaptions(ctx, scene.captions, this.groups, this.kw, t)

    const bounds: Bounds[] = []
    for (const ly of scene.layers) {
      const a = layerAnim(ly, t, d)
      if (!a.visible) continue
      const img = this.layerImage(ly)
      if (!img) continue
      const w = img.width * a.s
      const h = img.height * a.s
      const cx = ly.x * W + a.dx
      const cy = ly.y * H + a.dy
      ctx.save()
      ctx.globalAlpha = a.alpha
      ctx.drawImage(img, cx - w / 2, cy - h / 2, w, h)
      ctx.restore()
      bounds.push({
        id: ly.id,
        x: cx - img.width / 2,
        y: cy - img.height / 2,
        w: img.width,
        h: img.height,
      })
    }
    this.bounds = bounds

    if (fx.flash && moments.length) {
      const k = decay(0.15)
      if (k > 0) {
        ctx.save()
        ctx.globalAlpha = Math.min(0.6, 0.3 * k)
        ctx.fillStyle = '#fff'
        ctx.fillRect(0, 0, W, H)
        ctx.restore()
      }
    }
    if (fx.glitch && within(0.12)) {
      ctx.save()
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.globalAlpha = 0.35
      ctx.globalCompositeOperation = 'screen'
      ctx.drawImage(this.canvas, 14 * this.resolution, 0)
      ctx.drawImage(this.canvas, -14 * this.resolution, 0)
      ctx.restore()
    }
  }
}
