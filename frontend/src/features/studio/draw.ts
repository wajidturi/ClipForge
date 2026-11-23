/**
 * Canvas twin of backend `pipeline/render/raster.py` + `scene.panels`: same
 * constants, same shape points, same fonts (loaded from /api/v1/fonts/{id}), so the
 * studio preview matches the exported video. Change both sides together.
 */
import type { Layer, Scene } from '@/lib/api/client'

export const W = 1080
export const H = 1920

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
  const g = r.frame.style !== 'none' ? r.frame.gap : 0
  if (t === 'streamer_first' || t === 'gameplay_first' || t === 'dual_vision') {
    const topH = even(H * r.split)
    const top = { x: g, y: g, w: even(W - 2 * g), h: even(topH - g - g / 2) }
    const bottom = {
      x: g,
      y: even(topH + g / 2),
      w: even(W - 2 * g),
      h: even(H - topH - g - g / 2),
    }
    return t === 'gameplay_first' ? { game: top, cam: bottom } : { cam: top, game: bottom }
  }
  const out: Record<string, Rect> = { game: { x: g, y: g, w: even(W - 2 * g), h: even(H - 2 * g) } }
  if (t === 'floating_facecam' && r.cam.visible) {
    const side = even(W * r.cam.size)
    out.cam = {
      x: Math.round(r.cam.x * W - side / 2),
      y: Math.round(r.cam.y * H - side / 2),
      w: side,
      h: side,
    }
  }
  return out
}

export function coverCrop(
  box: number[],
  aspect: number,
  srcW: number,
  srcH: number,
): [number, number, number, number] {
  const [bx, by, bw, bh] = box as [number, number, number, number]
  let cw = bw * srcW
  let ch = bh * srcH
  if (cw / ch < aspect) cw = ch * aspect
  else ch = cw / aspect
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

export function renderTextLayer(layer: Layer, rawText: string): HTMLCanvasElement {
  const px = Math.max(8, Math.round(layer.size * layer.scale))
  const fontId = layer.kind === 'emoji' ? 'emoji' : layer.font
  const text = layer.upper && layer.kind === 'text' ? rawText.toUpperCase() : rawText
  const [, probe] = canvas(1, 1)
  const lines = layoutLines(probe, text || ' ', fontId, px, layer.max_width * W)
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
) {
  const w = Math.max(4, Math.round(layer.width * W * layer.scale))
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
  const yc = H * scene.regions.split
  const half = dv.thickness / 2
  const dy = (Math.tan((dv.tilt * Math.PI) / 180) * W) / 2
  return [
    [-10, yc - half + dy],
    [W + 10, yc - half - dy],
    [W + 10, yc + half - dy],
    [-10, yc + half + dy],
  ]
}

let vignetteCache: HTMLCanvasElement | null = null
function vignette(): HTMLCanvasElement {
  if (vignetteCache) return vignetteCache
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
  vignetteCache = c
  return c
}

/** Like raster.frame_image: background around panels, neon borders, cam ring,
 * divider, letterbox, vignette. Returns null when there is nothing to draw. */
export function frameCanvas(scene: Scene): HTMLCanvasElement | null {
  const r = scene.regions
  const fx = scene.effects
  const fr = r.frame
  const p = panels(scene)
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
  if (scene.template === 'dual_vision' && r.divider.style !== 'none') {
    const dv = r.divider
    const pts = dividerPoints(scene)
    if (dv.style === 'line') {
      const yc = H * r.split
      const dy = (Math.tan((dv.tilt * Math.PI) / 180) * W) / 2
      ctx.strokeStyle = dv.color
      ctx.lineWidth = Math.max(4, Math.floor(dv.thickness / 8))
      ctx.beginPath()
      ctx.moveTo(0, yc + dy)
      ctx.lineTo(W, yc - dy)
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
      const grad = ctx.createLinearGradient(0, 0, W, 0)
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
    ctx.drawImage(vignette(), 0, 0)
    drew = true
  }
  return drew ? c : null
}

let speedCache: HTMLCanvasElement | null = null
export function speedLines(): HTMLCanvasElement {
  if (speedCache) return speedCache
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
  speedCache = c
  return c
}
