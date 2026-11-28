/**
 * Canvas twin of backend `pipeline/render/raster.py` + `scene.panels`: same
 * constants, same shape points, same fonts (loaded from /api/v1/fonts/{id}), so the
 * studio preview matches the exported video. Change both sides together.
 */
import type { Layer, Scene } from '@/lib/api/client'

export const W = 1080 // default (9:16) design canvas
export const H = 1920

/** Like scene.design_size: the canvas everything is drawn on, short side 1080. */
export function designSize(scene: Scene): [number, number] {
  const c = scene.canvas ?? { w: W, h: H }
  const k = 1080 / Math.min(c.w, c.h)
  return [even(c.w * k), even(c.h * k)]
}

export type Rect = { x: number; y: number; w: number; h: number }
type Ctx2D = CanvasRenderingContext2D

// ------------------------------------------------------------------ fonts
const loaded = new Map<string, Promise<void>>()
export const family = (id: string) => `cf-${id}`

export function loadFont(id: string): Promise<void> {
  if (typeof FontFace === 'undefined') return Promise.resolve() // very old browsers, tests
  let p = loaded.get(id)
  if (!p) {
    const face = new FontFace(family(id), `url(/api/v1/fonts/${id})`)
    p = face
      .load()
      .then((f) => {
        document.fonts.add(f)
      })
      .catch(() => undefined)
    loaded.set(id, p)
  }
  return p
}

export function loadFonts(ids: Iterable<string>): Promise<void> {
  return Promise.all([...new Set([...ids, 'emoji'])].map(loadFont)).then(() => undefined)
}

// ------------------------------------------------------------------ geometry
export const even = (v: number) => Math.max(2, Math.floor(Math.round(v) / 2) * 2)

export function panels(scene: Scene): Record<string, Rect> {
  const r = scene.regions
  const t = scene.template
  const [W, H] = designSize(scene)
  const g = r.frame.style !== 'none' ? r.frame.gap : 0
  if (t === 'streamer_first' || t === 'gameplay_first' || t === 'dual_vision') {
    let first: Rect
    let second: Rect
    if (W > H) {
      // landscape: side by side, the first panel on the left
      const leftW = even(W * r.split)
      first = { x: g, y: g, w: even(leftW - g - g / 2), h: even(H - 2 * g) }
      second = { x: even(leftW + g / 2), y: g, w: even(W - leftW - g - g / 2), h: even(H - 2 * g) }
    } else {
      const topH = even(H * r.split)
      first = { x: g, y: g, w: even(W - 2 * g), h: even(topH - g - g / 2) }
      second = { x: g, y: even(topH + g / 2), w: even(W - 2 * g), h: even(H - topH - g - g / 2) }
    }
    return placed(
      scene,
      t === 'gameplay_first' ? { game: first, cam: second } : { cam: first, game: second },
    )
  }
  const out: Record<string, Rect> = { game: { x: g, y: g, w: even(W - 2 * g), h: even(H - 2 * g) } }
  if (t === 'floating_facecam' && r.cam.visible) {
    const side = even(Math.min(W, H) * r.cam.size)
    out.cam = {
      x: Math.round(r.cam.x * W - side / 2),
      y: Math.round(r.cam.y * H - side / 2),
      w: side,
      h: side,
    }
  }
  return placed(scene, out)
}

export type Spot = { x: number; y: number; w: number; h: number }

/** Like scene.spot_rect: a freely placed panel (fractions of the video) in pixels. */
export function spotRect(sp: Spot, W: number, H: number): Rect {
  return {
    x: Math.round(sp.x * W),
    y: Math.round(sp.y * H),
    w: Math.max(16, even(sp.w * W)),
    h: Math.max(16, even(sp.h * H)),
  }
}

/** The panels after the studio's free layout (regions.place), like scene.panels. */
function placed(scene: Scene, out: Record<string, Rect>): Record<string, Rect> {
  const pl = scene.regions.place
  if (!pl) return out
  const [W, H] = designSize(scene)
  if (pl.game) out.game = spotRect(pl.game, W, H)
  if (pl.cam && out.cam && scene.template !== 'floating_facecam') out.cam = spotRect(pl.cam, W, H)
  return out
}

/** Like scene.free_layout: has the user moved a panel? */
export function freeLayout(scene: Scene): boolean {
  const pl = scene.regions.place
  return !!pl && (!!pl.game || !!pl.cam)
}

/** A panel rect back to a Spot (fractions), within the model's limits. */
export function toSpot(r: Rect, W: number, H: number): Spot {
  const c = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
  return {
    x: c(r.x / W, -0.9, 0.9),
    y: c(r.y / H, -0.9, 0.9),
    w: c(r.w / W, 0.1, 1.5),
    h: c(r.h / H, 0.1, 1.5),
  }
}

export const TILE_GAP = 8 // px between people sharing the facecam panel

/** Like scene.cam_tiles: split the facecam panel into n side-by-side tiles. */
export function camTiles(rect: Rect, n: number, gap = TILE_GAP): Rect[] {
  if (n <= 1) return n === 1 ? [rect] : []
  if (rect.h > rect.w) {
    // a tall panel (landscape layouts): one above the other
    const h = even((rect.h - gap * (n - 1)) / n)
    const rows: Rect[] = []
    for (let i = 0; i < n - 1; i++)
      rows.push({ x: rect.x, y: rect.y + i * (h + gap), w: rect.w, h })
    const lastY = rect.y + (n - 1) * (h + gap)
    rows.push({ x: rect.x, y: lastY, w: rect.w, h: even(rect.y + rect.h - lastY) })
    return rows
  }
  const w = even((rect.w - gap * (n - 1)) / n)
  const out: Rect[] = []
  for (let i = 0; i < n - 1; i++) out.push({ x: rect.x + i * (w + gap), y: rect.y, w, h: rect.h })
  const lastX = rect.x + (n - 1) * (w + gap)
  out.push({ x: lastX, y: rect.y, w: even(rect.x + rect.w - lastX), h: rect.h })
  return out
}

/** Like CutPlan.cam_list: everyone in stacked templates, the main person in the bubble. */
export function camList(
  cut: { cam?: number[] | null; cams?: number[][]; primary?: number },
  template: string,
): number[][] {
  const cams = cut.cams?.length ? cut.cams : cut.cam ? [cut.cam] : []
  if (template === 'floating_facecam') {
    const main = cams[cut.primary ?? 0] ?? cams[0]
    return main ? [main] : []
  }
  return cams
}

export const CAM_MAX_GROW = 1.3 // like scene.CAM_MAX_GROW

/** Like scene.cover_crop (with its max_grow for facecam tiles). */
export function coverCrop(
  box: number[],
  aspect: number,
  srcW: number,
  srcH: number,
  maxGrow?: number,
): [number, number, number, number] {
  const [bx, by, bw, bh] = box as [number, number, number, number]
  let cw = bw * srcW
  let ch = bh * srcH
  if (cw / ch < aspect) {
    if (maxGrow && ch * aspect > cw * maxGrow) {
      cw = cw * maxGrow
      ch = cw / aspect
    } else cw = ch * aspect
  } else if (maxGrow && cw / aspect > ch * maxGrow) {
    ch = ch * maxGrow
    cw = ch * aspect
  } else ch = cw / aspect
  if (cw > srcW) {
    cw = srcW
    ch = srcW / aspect
  }
  if (ch > srcH) {
    ch = srcH
    cw = srcH * aspect
  }
  const cx = (bx + bw / 2) * srcW
  const cy = (by + bh / 2) * srcH
  const x = Math.min(Math.max(cx - cw / 2, 0), srcW - cw)
  const y = Math.min(Math.max(cy - ch / 2, 0), srcH - ch)
  return [Math.trunc(x), Math.trunc(y), even(cw), even(ch)]
}

/** Like matte.matte_crop: a source-pixel crop in matte pixels. */
export function matteCrop(
  rect: number[],
  srcW: number,
  srcH: number,
  mw: number,
  mh: number,
): [number, number, number, number] {
  const [x, y, w, h] = rect as [number, number, number, number]
  const fx = mw / srcW
  const fy = mh / srcH
  const cw = Math.max(2, Math.floor(Math.trunc(w * fx) / 2) * 2)
  const ch = Math.max(2, Math.floor(Math.trunc(h * fy) / 2) * 2)
  const cx = Math.min(Math.max(0, Math.trunc(x * fx)), mw - cw)
  const cy = Math.min(Math.max(0, Math.trunc(y * fy)), mh - ch)
  return [cx, cy, cw, ch]
}

const HIDE_GROW = 1.15
const floorEven = (v: number) => Math.max(2, Math.floor(Math.trunc(v) / 2) * 2) // compose._even

/** Like scene_render.hide_rects: facecam overlays (source px) to blur in the gameplay. */
export function hideRects(cams: number[][], srcW: number, srcH: number): number[][] {
  const out: number[][] = []
  for (const [bx, by, bw, bh] of cams as [number, number, number, number][]) {
    const w0 = Math.min(1, bw * HIDE_GROW)
    const h0 = Math.min(1, bh * HIDE_GROW)
    const x0 = Math.min(Math.max(0, bx + bw / 2 - w0 / 2), 1 - w0)
    const y0 = Math.min(Math.max(0, by + bh / 2 - h0 / 2), 1 - h0)
    const x = Math.trunc(x0 * srcW)
    const y = Math.trunc(y0 * srcH)
    const w = floorEven(Math.min(w0 * srcW, srcW - x))
    const h = floorEven(Math.min(h0 * srcH, srcH - y))
    if (w >= 8 && h >= 8) out.push([x, y, w, h])
  }
  return out
}

// ------------------------------------------------------------------ text
export function isEmoji(ch: string): boolean {
  const o = ch.codePointAt(0) ?? 0
  return (
    o >= 0x1f000 ||
    (o >= 0x2600 && o <= 0x27bf) ||
    (o >= 0x2b00 && o <= 0x2bff) ||
    [0x200d, 0xfe0f, 0x2122, 0x2139].includes(o)
  )
}

export function runs(text: string): [string, boolean][] {
  const out: [string, boolean][] = []
  for (const ch of Array.from(text)) {
    const last = out[out.length - 1]
    const e = isEmoji(ch) || ('‍️'.includes(ch) && !!last && last[1])
    if (last && last[1] === e) last[0] += ch
    else out.push([ch, e])
  }
  return out
}

const font = (id: string, px: number) => `${px}px "${family(id)}"`

function measure(ctx: Ctx2D, text: string, fontId: string, px: number): number {
  let total = 0
  for (const [chunk, emo] of runs(text)) {
    ctx.font = font(emo ? 'emoji' : fontId, px)
    total += ctx.measureText(chunk).width
  }
  return total
}

type Line = { text: string; width: number }

function layoutLines(ctx: Ctx2D, text: string, fontId: string, px: number, maxW: number): Line[] {
  const lines: Line[] = []
  for (const para of text.split('\n')) {
    let cur = ''
    for (const word of para.split(' ')) {
      const trial = cur ? `${cur} ${word}` : word
      if (cur && measure(ctx, trial, fontId, px) > maxW) {
        lines.push({ text: cur, width: measure(ctx, cur, fontId, px) })
        cur = word
      } else cur = trial
    }
    lines.push({ text: cur, width: measure(ctx, cur, fontId, px) })
  }
  return lines
}

export function shapePoints(shape: string, w: number, h: number): [number, number][] {
  if (shape === 'ribbon') {
    const sk = 0.35 * h
    return [
      [sk, 0],
      [w, 0],
      [w - sk, h],
      [0, h],
    ]
  }
  if (shape === 'burst') {
    const n = 16
    const pts: [number, number][] = []
    for (let k = 0; k < n * 2; k++) {
      const a = -Math.PI / 2 + (k * Math.PI) / n
      const r = k % 2 === 0 ? (Math.floor(k / 2) % 2 === 0 ? 1 : 0.9) : 0.78
      pts.push([w / 2 + ((Math.cos(a) * w) / 2) * r, h / 2 + ((Math.sin(a) * h) / 2) * r])
    }
    return pts
  }
  return []
}

function shapeBox(shape: string, tw: number, th: number, px: number) {
  if (shape === 'none') return { sw: tw, sh: th, ox: 0, oy: 0 }
  const [padX, padY] = shape === 'tag' ? [0.32 * px, 0.16 * px] : [0.42 * px, 0.22 * px]
  let sw: number
  let sh: number
  if (shape === 'burst') {
    sw = (tw + 2 * padX) * 1.38
    sh = (th + 2 * padY) * 1.8
  } else if (shape === 'ribbon') {
    const sk = 0.35 * (th + 2 * padY)
    sw = tw + 2 * padX + sk
    sh = th + 2 * padY
  } else {
    sw = tw + 2 * padX
    sh = th + 2 * padY
  }
  return { sw, sh, ox: (sw - tw) / 2, oy: (sh - th) / 2 }
}

function canvas(w: number, h: number): [HTMLCanvasElement, Ctx2D] {
  const c = document.createElement('canvas')
  c.width = Math.max(1, Math.ceil(w))
  c.height = Math.max(1, Math.ceil(h))
  return [c, c.getContext('2d')!]
}

function roundRectPath(ctx: Ctx2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.roundRect(x, y, w, h, Math.max(0, Math.min(r, w / 2, h / 2)))
}

/** Shear (italic) then rotate around the centre, then opacity: like raster._shear_rotate. */
function finish(src: HTMLCanvasElement, italic: boolean, rotation: number, opacity: number) {
  let img = src
  if (italic) {
    const k = 0.21
    const extra = Math.trunc(img.height * k) + 2
    const [c, x] = canvas(img.width + extra, img.height)
    x.setTransform(1, 0, -k, 1, (k * c.height) / 2, 0)
    x.drawImage(img, Math.floor(extra / 2), 0)
    img = c
  }
  if (rotation) {
    const a = (rotation * Math.PI) / 180
    const w = Math.abs(img.width * Math.cos(a)) + Math.abs(img.height * Math.sin(a))
    const h = Math.abs(img.width * Math.sin(a)) + Math.abs(img.height * Math.cos(a))
    const [c, x] = canvas(w, h)
    x.translate(c.width / 2, c.height / 2)
    x.rotate(a)
    x.drawImage(img, -img.width / 2, -img.height / 2)
    img = c
  }
  if (opacity < 0.999) {
    const [c, x] = canvas(img.width, img.height)
    x.globalAlpha = opacity
    x.drawImage(img, 0, 0)
    img = c
  }
  return img
}

export function renderTextLayer(layer: Layer, rawText: string, canvasW = W): HTMLCanvasElement {
  const px = Math.max(8, Math.round(layer.size * layer.scale))
  const fontId = layer.kind === 'emoji' ? 'emoji' : layer.font
  const text = layer.upper && layer.kind === 'text' ? rawText.toUpperCase() : rawText
  const [, probe] = canvas(1, 1)
  const lines = layoutLines(probe, text || ' ', fontId, px, layer.max_width * canvasW)
  const lh = px * 1.1
  const tw = Math.max(...lines.map((l) => l.width))
  const th = lh * lines.length
  const { sw, sh, ox, oy } = shapeBox(layer.shape, tw, th, px)
  const margin = Math.trunc(layer.stroke + px * 0.2 + 8)
  const [c, ctx] = canvas(Math.trunc(sw + 2 * margin), Math.trunc(sh + 2 * margin))
  const x0 = margin
  const y0 = margin
  if (layer.shape !== 'none') {
    const sstroke = layer.shape_stroke ? Math.max(3, Math.trunc(px * 0.06)) : 0
    ctx.fillStyle = layer.shape_color
    if (layer.shape === 'ribbon' || layer.shape === 'burst') {
      const pts = shapePoints(layer.shape, sw, sh)
      ctx.beginPath()
      pts.forEach(([a, b], i) => (i ? ctx.lineTo(x0 + a, y0 + b) : ctx.moveTo(x0 + a, y0 + b)))
      ctx.closePath()
    } else {
      const radius = layer.shape === 'pill' ? sh / 2 : (layer.shape === 'tag' ? 0.12 : 0.2) * px
      roundRectPath(ctx, x0, y0, sw, sh, radius)
    }
    ctx.fill()
    if (sstroke && layer.shape_stroke) {
      ctx.save()
      ctx.clip()
      ctx.lineWidth = sstroke * 2 // inside only, like Pillow's outline
      ctx.strokeStyle = layer.shape_stroke
      ctx.stroke()
      ctx.restore()
    }
  }
  const drawRuns = (target: Ctx2D, dy: number, shadow: boolean) => {
    lines.forEach((ln, i) => {
      let cx = x0 + ox + (tw - ln.width) / 2
      const base = y0 + oy + i * lh + px * 0.86 + dy
      for (const [chunk, emo] of runs(ln.text)) {
        target.font = font(emo ? 'emoji' : fontId, px)
        target.textBaseline = 'alphabetic'
        if (emo) {
          if (!shadow) target.fillText(chunk, cx, base)
        } else {
          if (layer.stroke > 0) {
            target.lineJoin = 'round'
            target.lineWidth = layer.stroke * 2
            target.strokeStyle = shadow ? 'rgba(0,0,0,0.59)' : layer.stroke_color
            target.strokeText(chunk, cx, base)
          }
          target.fillStyle = shadow ? 'rgba(0,0,0,0.59)' : layer.color
          target.fillText(chunk, cx, base)
        }
        cx += target.measureText(chunk).width
      }
    })
  }
  if (layer.shadow) {
    const [sc, sctx] = canvas(c.width, c.height)
    drawRuns(sctx, px * 0.06, true)
    ctx.save()
    ctx.filter = `blur(${px * 0.05}px)`
    ctx.drawImage(sc, 0, 0)
    ctx.restore()
  }
  drawRuns(ctx, 0, false)
  return finish(c, layer.italic, layer.rotation, layer.opacity)
}

export function renderImageLayer(
  layer: Layer,
  img: CanvasImageSource & { width: number; height: number },
  canvasW = W,
) {
  const w = Math.max(4, Math.round(layer.width * canvasW * layer.scale))
  const h = Math.max(4, Math.round((img.height * w) / img.width))
  const [c, ctx] = canvas(w, h)
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(img, 0, 0, w, h)
  return finish(c, false, layer.rotation, layer.opacity)
}

// ------------------------------------------------------------------ template graphics
function insetStroke(
  ctx: Ctx2D,
  r: Rect,
  radius: number,
  color: string,
  color2: string,
  width: number,
  glow: number,
  circle = false,
) {
  if (width <= 0) return
  const path = (inset: number) => {
    if (circle) {
      ctx.beginPath()
      ctx.ellipse(r.x + r.w / 2, r.y + r.h / 2, r.w / 2 - inset, r.h / 2 - inset, 0, 0, Math.PI * 2)
    } else
      roundRectPath(ctx, r.x + inset, r.y + inset, r.w - 2 * inset, r.h - 2 * inset, radius - inset)
  }
  if (glow > 0) {
    const gw = width + Math.floor(glow / 2)
    ctx.save()
    ctx.filter = `blur(${glow / 2}px)`
    ctx.strokeStyle = color2
    ctx.lineWidth = gw
    path(gw / 2)
    ctx.stroke()
    ctx.restore()
  }
  ctx.strokeStyle = color
  ctx.lineWidth = width
  path(width / 2)
  ctx.stroke()
}

export function dividerPoints(scene: Scene): [number, number][] {
  const dv = scene.regions.divider
  const [W, H] = designSize(scene)
  const half = dv.thickness / 2
  if (W > H) {
    // landscape: a vertical band
    const xc = W * scene.regions.split
    const dx = (Math.tan((dv.tilt * Math.PI) / 180) * H) / 2
    return [
      [xc - half + dx, -10],
      [xc - half - dx, H + 10],
      [xc + half - dx, H + 10],
      [xc + half + dx, -10],
    ]
  }
  const yc = H * scene.regions.split
  const dy = (Math.tan((dv.tilt * Math.PI) / 180) * W) / 2
  return [
    [-10, yc - half + dy],
    [W + 10, yc - half - dy],
    [W + 10, yc + half - dy],
    [-10, yc + half + dy],
  ]
}

const vignetteCache = new Map<string, HTMLCanvasElement>()
function vignette(W: number, H: number): HTMLCanvasElement {
  const hit = vignetteCache.get(`${W}x${H}`)
  if (hit) return hit
  const [c, ctx] = canvas(W, H)
  const img = ctx.createImageData(W, H)
  for (let y = 0; y < H; y++) {
    const dy = (y - H / 2) / (H / 2)
    for (let x = 0; x < W; x++) {
      const dx = (x - W / 2) / (W / 2)
      const d = Math.sqrt(dx * dx + dy * dy) / Math.SQRT2
      const a = Math.min(1, Math.max(0, (d - 0.45) / 0.55)) ** 1.6 * 200
      img.data[(y * W + x) * 4 + 3] = a
    }
  }
  ctx.putImageData(img, 0, 0)
  vignetteCache.set(`${W}x${H}`, c)
  return c
}

/** Like raster.frame_image: background around panels, neon borders, cam ring,
 * divider, letterbox, vignette. Returns null when there is nothing to draw. */
export function frameCanvas(scene: Scene): HTMLCanvasElement | null {
  const r = scene.regions
  const fx = scene.effects
  const fr = r.frame
  const p = panels(scene)
  const [W, H] = designSize(scene)
  const [c, ctx] = canvas(W, H)
  const stacked = ['streamer_first', 'gameplay_first', 'dual_vision'].includes(scene.template)
  let drew = false
  if (fr.style !== 'none' && (stacked || fr.gap > 0 || fr.radius > 0)) {
    ctx.fillStyle = fr.background
    ctx.fillRect(0, 0, W, H)
    ctx.globalCompositeOperation = 'destination-out'
    for (const key of stacked ? ['game', 'cam'] : ['game']) {
      const q = p[key]!
      roundRectPath(ctx, q.x, q.y, q.w, q.h, fr.radius)
      ctx.fill()
    }
    ctx.globalCompositeOperation = 'source-over'
    drew = true
  }
  if (fr.style !== 'none') {
    for (const key of stacked ? ['cam', 'game'] : ['game'])
      insetStroke(
        ctx,
        p[key]!,
        fr.radius,
        fr.color,
        fr.color2,
        fr.width,
        fr.style === 'neon' ? fr.glow : 0,
      )
    drew = true
  }
  if (scene.template === 'floating_facecam' && p.cam && r.cam.border_width > 0) {
    const cr = r.cam
    const radius = cr.shape === 'square' ? 0 : Math.trunc(p.cam.w * 0.22)
    insetStroke(
      ctx,
      p.cam,
      radius,
      cr.border_color,
      cr.border_color,
      cr.border_width,
      cr.glow,
      cr.shape === 'circle',
    )
    drew = true
  }
  if (scene.template === 'dual_vision' && r.divider.style !== 'none' && !freeLayout(scene)) {
    const dv = r.divider
    const pts = dividerPoints(scene)
    if (dv.style === 'line') {
      // the centre line of the band (like raster._divider)
      const [a, b, cc, e] = pts as [
        [number, number],
        [number, number],
        [number, number],
        [number, number],
      ]
      ctx.strokeStyle = dv.color
      ctx.lineWidth = Math.max(4, Math.floor(dv.thickness / 8))
      ctx.beginPath()
      ctx.moveTo((a[0] + e[0]) / 2, (a[1] + e[1]) / 2)
      ctx.lineTo((b[0] + cc[0]) / 2, (b[1] + cc[1]) / 2)
      ctx.stroke()
    } else {
      const poly = () => {
        ctx.beginPath()
        pts.forEach(([a, b], i) => (i ? ctx.lineTo(a, b) : ctx.moveTo(a, b)))
        ctx.closePath()
      }
      if (dv.style === 'ribbon') {
        ctx.save()
        ctx.filter = 'blur(14px)'
        ctx.globalAlpha = 0.8
        ctx.fillStyle = dv.color2
        poly()
        ctx.fill()
        ctx.restore()
      }
      const grad =
        W > H ? ctx.createLinearGradient(0, 0, 0, H) : ctx.createLinearGradient(0, 0, W, 0)
      grad.addColorStop(0, dv.color)
      grad.addColorStop(1, dv.color2)
      ctx.fillStyle = grad
      poly()
      ctx.fill()
      ctx.strokeStyle = 'rgba(255,255,255,0.78)'
      ctx.lineWidth = 3
      ctx.beginPath()
      ctx.moveTo(...pts[0]!)
      ctx.lineTo(...pts[1]!)
      ctx.moveTo(...pts[3]!)
      ctx.lineTo(...pts[2]!)
      ctx.stroke()
    }
    drew = true
  }
  if (fx.letterbox) {
    const bar = Math.trunc(H * 0.085)
    ctx.fillStyle = '#000'
    ctx.fillRect(0, 0, W, bar + 1)
    ctx.fillRect(0, H - bar, W, bar)
    drew = true
  }
  if (fx.vignette) {
    ctx.drawImage(vignette(W, H), 0, 0)
    drew = true
  }
  return drew ? c : null
}

const speedCache = new Map<string, HTMLCanvasElement>()
export function speedLines(W: number = 1080, H: number = 1920): HTMLCanvasElement {
  const hit = speedCache.get(`${W}x${H}`)
  if (hit) return hit
  const [c, ctx] = canvas(W, H)
  ctx.strokeStyle = 'rgba(255,255,255,0.59)'
  for (let k = 0; k < 64; k++) {
    const a = (((k * 137.508) % 360) * Math.PI) / 180
    const r0 = 380 + ((k * 53) % 260)
    const r1 = r0 + 420 + ((k * 97) % 600)
    ctx.lineWidth = 3 + (k % 4)
    ctx.beginPath()
    ctx.moveTo(W / 2 + Math.cos(a) * r0, H / 2 + Math.sin(a) * r0)
    ctx.lineTo(W / 2 + Math.cos(a) * r1, H / 2 + Math.sin(a) * r1)
    ctx.stroke()
  }
  speedCache.set(`${W}x${H}`, c)
  return c
}
