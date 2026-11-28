/**
 * Video Review & Customisation Studio: live canvas preview of the scene over the
 * prepared cut, drag/resize on the canvas, template-aware panels, undo/redo, and a
 * re-render that creates a new version (nothing is ever overwritten).
 */
import {
  Clapperboard,
  Layers,
  LayoutTemplate,
  Loader2,
  Pause,
  Play,
  Plus,
  Redo2,
  RotateCcw,
  Sparkles,
  Subtitles,
  Undo2,
  Volume2,
  VolumeX,
  Wand2,
} from 'lucide-react'
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent,
  type CSSProperties,
} from 'react'
import { useTranslation } from 'react-i18next'
import { Badge, Button, Card, Progress } from '@/components/ui'
import {
  mediaUrl,
  type Scene,
  type ShortDetail,
  type StudioData,
  type TemplateChoice,
} from '@/lib/api/client'
import { useJob } from '@/lib/jobs'
import { useRenderOptions } from '@/lib/runs'
import { useRenderOne } from '@/lib/shorts'
import { useHistory, useStudio, useSwitchTemplate } from '@/lib/studio'
import { cn, formatClock } from '@/lib/utils'
import { Compositor } from './compositor'
import { Segmented } from './controls'
import { designSize, loadFonts, panels, toSpot, type Rect } from './draw'
import { limitsOf } from './canvas'
import { removeLayer, setLayer, type Edit } from './edit'
import {
  AddPanel,
  CaptionsPanel,
  EffectsPanel,
  ElementsPanel,
  Inspector,
  TemplatePanel,
} from './panels'
import { TemplatePicker } from './TemplatePicker'

const TABS = [
  { id: 'template', icon: LayoutTemplate },
  { id: 'elements', icon: Layers },
  { id: 'add', icon: Plus },
  { id: 'captions', icon: Subtitles },
  { id: 'effects', icon: Sparkles },
] as const
type Tab = (typeof TABS)[number]['id']

function RenderProgress({ short }: { short: ShortDetail }) {
  const { t } = useTranslation()
  const job = useJob(short.status === 'rendering' ? short.render_job_id : null)
  if (short.status !== 'rendering') return null
  return (
    <div className="flex min-w-48 flex-col gap-1">
      <Progress value={job.data?.progress ?? 0} />
      <span className="text-[11px] text-muted">{job.data?.step ?? t('render.queued')}</span>
    </div>
  )
}

/** First render: pick a template and generate (the editor needs a prepared cut). */
function Generate({ short }: { short: ShortDetail }) {
  const { t } = useTranslation()
  const opts = useRenderOptions()
  const render = useRenderOne(short.id)
  const [tpl, setTpl] = useState<TemplateChoice>('auto')
  return (
    <Card className="mx-auto max-w-3xl space-y-5 p-6">
      <div>
        <h2 className="text-lg font-semibold">{t('cz.generate.title')}</h2>
        <p className="mt-1 text-sm text-muted">
          {short.active ? t('cz.generate.legacy') : t('cz.generate.body')}
        </p>
      </div>
      {opts.data && (
        <TemplatePicker value={tpl} onChange={setTpl} templates={opts.data.templates} withAuto />
      )}
      <div className="flex items-center gap-3">
        <Button
          onClick={() => render.mutate({ template: tpl })}
          disabled={render.isPending || short.status === 'rendering'}
        >
          <Wand2 size={15} aria-hidden /> {t('cz.generate.go')}
        </Button>
        <RenderProgress short={short} />
      </div>
      {render.error && <p className="text-sm text-danger">{render.error.message}</p>}
    </Card>
  )
}

/** The preview keeps the video's shape: as tall as the screen allows (760 px at most),
 *  never wider than its column; the height follows from the aspect ratio. */
function previewBox(w: number, h: number): CSSProperties {
  return { aspectRatio: `${w} / ${h}`, width: `min(100%, calc(min(72vh, 760px) * ${w / h}))` }
}

const PANEL_KEY = { __game: 'game', __panel: 'cam' } as const
type PanelId = keyof typeof PANEL_KEY
const isPanel = (id: string | null): id is PanelId => id === '__game' || id === '__panel'

/** Snap a dragged panel to the video's edges and centre lines (within 18 px). */
function snapRect(r: Rect, W: number, H: number): Rect {
  const near = (v: number, targets: number[]) =>
    targets.reduce((best, t) => (Math.abs(v - t) < Math.abs(v - best) ? t : best), v)
  const pick = (v: number, targets: number[]) => {
    const t = near(v, targets)
    return Math.abs(v - t) <= 18 ? t : v
  }
  return {
    ...r,
    x: Math.round(pick(r.x, [0, W - r.w, (W - r.w) / 2])),
    y: Math.round(pick(r.y, [0, H - r.h, (H - r.h) / 2])),
  }
}

export function Customizer({ short }: { short: ShortDetail }) {
  const studio = useStudio(short.id)
  const opts = useRenderOptions()
  if (studio.isLoading || !opts.data) return <p className="p-6 text-sm text-muted">…</p>
  if (studio.isError || !studio.data)
    return <p className="p-6 text-sm text-danger">{studio.error?.message}</p>
  if (!studio.data.cut) return <Generate short={short} />
  return (
    <Editor
      key={studio.data.cut.key}
      short={short}
      data={studio.data as unknown as StudioData}
      fonts={opts.data.fonts}
      templates={opts.data.templates}
      presets={opts.data.caption_presets as Edit['presets']}
      backgrounds={opts.data.cam_backgrounds ?? []}
      canvases={opts.data.canvases ?? []}
      canvasLimits={limitsOf(opts.data.canvas_limits)}
    />
  )
}

function Editor({
  short,
  data,
  fonts,
  templates,
  presets,
  backgrounds,
  canvases,
  canvasLimits,
}: {
  short: ShortDetail
  data: StudioData
  fonts: Edit['fonts']
  templates: Parameters<typeof TemplatePicker>[0]['templates']
  presets: Edit['presets']
  backgrounds: Edit['backgrounds']
  canvases: Edit['canvases']
  canvasLimits: Edit['canvasLimits']
}) {
  const { t } = useTranslation()
  const cut = data.cut!
  const saved = data.scene as Scene
  const hist = useHistory<Scene>(saved)
  const scene = hist.value
  const [W, H] = designSize(scene) // drawing units of this video size
  const [tab, setTab] = useState<Tab>('template')
  const [selected, setSelected] = useState<string | null>(null)
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(false)
  const [view, setView] = useState<'live' | 'rendered'>('live')
  const [fontsReady, setFontsReady] = useState(0)
  const wide = useWide()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const matteRef = useRef<HTMLVideoElement>(null)
  const selRef = useRef<HTMLDivElement>(null)
  const comp = useRef<Compositor | null>(null)
  const imagesRef = useRef(new Map<string, HTMLImageElement>())
  const [imgTick, setImgTick] = useState(0)
  const switchTpl = useSwitchTemplate(short.id)
  const render = useRenderOne(short.id)
  const dirty = JSON.stringify(scene) !== JSON.stringify(saved)
  const duration = cut.duration
  const keywords = short.keywords

  // ---------------------------------------------------------------- drawing
  const draw = useCallback(() => {
    const c = comp.current
    const v = videoRef.current
    if (!c || !v) return
    c.draw(v.currentTime)
    const box = selRef.current
    if (!box) return
    const b = c.bounds.find((x) => x.id === selected)
    const camBox =
      selected === '__cam'
        ? panels(scene).cam
        : isPanel(selected)
          ? panels(scene)[PANEL_KEY[selected]]
          : undefined
    const r = b ?? camBox
    if (!r) {
      box.style.display = 'none'
      return
    }
    box.style.display = 'block'
    box.style.left = `${(r.x / W) * 100}%`
    box.style.top = `${(r.y / H) * 100}%`
    box.style.width = `${(r.w / W) * 100}%`
    box.style.height = `${(r.h / H) * 100}%`
  }, [selected, scene, W, H])

  useEffect(() => {
    if (!canvasRef.current || !videoRef.current) return
    comp.current = new Compositor(canvasRef.current, videoRef.current, imagesRef.current)
    comp.current.setMatte(matteRef.current)
    comp.current.onAsset = () => setImgTick((n) => n + 1)
  }, [])

  useEffect(() => {
    comp.current?.setModel({
      scene,
      cut,
      values: data.values,
      overrides: data.caption_overrides,
      keywords,
    })
    draw()
  }, [scene, cut, data.values, data.caption_overrides, keywords, draw, fontsReady, imgTick])

  // fonts used by the scene (same files as the renderer)
  const fontKey = [scene.captions.font, ...scene.layers.map((l) => l.font)].sort().join(',')
  useEffect(() => {
    let live = true
    void loadFonts(fontKey.split(',')).then(() => {
      if (!live) return
      comp.current?.invalidate()
      setFontsReady((n) => n + 1)
    })
    return () => {
      live = false
    }
  }, [fontKey])

  // logos / images
  useEffect(() => {
    const images = imagesRef.current
    for (const l of scene.layers) {
      if (l.kind !== 'image' || !l.asset_id || images.has(l.asset_id)) continue
      const img = new Image()
      img.onload = () => setImgTick((n) => n + 1)
      img.src = mediaUrl(l.asset_id)
      images.set(l.asset_id, img)
    }
  }, [scene.layers])

  // playback loop
  useEffect(() => {
    if (!playing) return
    let raf = 0
    let last = 0
    const tick = (now: number) => {
      draw()
      if (now - last > 120) {
        last = now
        setTime(videoRef.current?.currentTime ?? 0)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, draw])

  const togglePlay = useCallback(() => {
    const v = videoRef.current
    if (!v) return
    if (v.paused)
      void v
        .play()
        .then(() => setPlaying(true))
        .catch(() => undefined)
    else {
      v.pause()
      setPlaying(false)
    }
  }, [])

  const seek = (s: number) => {
    const v = videoRef.current
    if (!v) return
    v.currentTime = Math.max(0, Math.min(duration - 0.01, s))
    setTime(v.currentTime)
  }

  // ---------------------------------------------------------------- editing
  const edit: Edit = {
    scene,
    update: (fn, transient) => hist.set((s) => fn(s), transient),
    commit: hist.commit,
    time,
    duration,
    selected,
    select: setSelected,
    fonts,
    presets,
    backgrounds,
    canvases,
    canvasLimits,
    cutOut: !!cut.matte_asset_id && (cut.cam_kind === 'overlay' || cut.cam_kind === 'camera'),
  }
  const layer = scene.layers.find((l) => l.id === selected) ?? null

  // free layout: the gameplay / facecam panel moved or resized (regions.place)
  const placePanel = (key: 'game' | 'cam', r: Rect, transient = false) =>
    hist.set(
      (s) => ({
        ...s,
        regions: {
          ...s.regions,
          place: { game: null, cam: null, ...s.regions.place, [key]: toSpot(r, W, H) },
        },
      }),
      transient,
    )

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const el = ev.target as HTMLElement | null
      if (
        el &&
        (el.tagName === 'INPUT' ||
          el.tagName === 'TEXTAREA' ||
          el.tagName === 'SELECT' ||
          el.isContentEditable)
      )
        return
      const mod = ev.ctrlKey || ev.metaKey
      if (mod && ev.key.toLowerCase() === 'z') {
        ev.preventDefault()
        if (ev.shiftKey) hist.redo()
        else hist.undo()
      } else if (mod && ev.key.toLowerCase() === 'y') {
        ev.preventDefault()
        hist.redo()
      } else if (ev.key === ' ') {
        ev.preventDefault()
        togglePlay()
      } else if (
        (ev.key === 'Delete' || ev.key === 'Backspace') &&
        selected &&
        selected !== '__cam' &&
        !isPanel(selected)
      ) {
        ev.preventDefault()
        removeLayer(edit, selected)
      } else if (ev.key === 'Escape') setSelected(null)
      else if (isPanel(selected) && ev.key.startsWith('Arrow')) {
        ev.preventDefault()
        const q = panels(scene)[PANEL_KEY[selected]]
        if (!q) return
        const step = Math.round((ev.shiftKey ? 0.02 : 0.003) * Math.min(W, H))
        const dx = ev.key === 'ArrowLeft' ? -step : ev.key === 'ArrowRight' ? step : 0
        const dy = ev.key === 'ArrowUp' ? -step : ev.key === 'ArrowDown' ? step : 0
        placePanel(PANEL_KEY[selected], { ...q, x: q.x + dx, y: q.y + dy })
      } else if (selected && selected !== '__cam' && ev.key.startsWith('Arrow')) {
        ev.preventDefault()
        const step = ev.shiftKey ? 0.02 : 0.003
        const l = scene.layers.find((x) => x.id === selected)
        if (!l) return
        const dx = ev.key === 'ArrowLeft' ? -step : ev.key === 'ArrowRight' ? step : 0
        const dy = ev.key === 'ArrowUp' ? -step : ev.key === 'ArrowDown' ? step : 0
        setLayer(edit, selected, { x: l.x + dx, y: l.y + dy })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  // drag to move, corner handle to resize (layers, the floating facecam, the panels)
  const drag = useRef<null | {
    rect?: Rect
    id: string
    mode: 'move' | 'scale'
    px: number
    py: number
    x: number
    y: number
    s: number
    cx: number
    cy: number
  }>(null)
  const toScene = (ev: PointerEvent) => {
    const r = canvasRef.current!.getBoundingClientRect()
    return [((ev.clientX - r.left) / r.width) * W, ((ev.clientY - r.top) / r.height) * H] as const
  }
  const onDown = (ev: PointerEvent<HTMLDivElement>) => {
    const c = comp.current
    if (!c || view !== 'live') return
    const [px, py] = toScene(ev)
    const hits = [...c.bounds].reverse()
    const sel = hits.find((b) => b.id === selected)
    const nearCorner = (b: { x: number; y: number; w: number; h: number }) =>
      Math.hypot(px - (b.x + b.w), py - (b.y + b.h)) < 48
    const p = panels(scene)
    const cam = scene.template === 'floating_facecam' ? p.cam : undefined
    const camPanel = scene.template !== 'floating_facecam' ? p.cam : undefined
    const inside = (b: Rect | undefined) =>
      !!b && px >= b.x && px <= b.x + b.w && py >= b.y && py <= b.y + b.h
    let id: string | null = null
    let mode: 'move' | 'scale' = 'move'
    const selPanel = isPanel(selected) ? p[PANEL_KEY[selected]] : undefined
    if (sel && nearCorner(sel)) {
      id = sel.id
      mode = 'scale'
    } else if (selected === '__cam' && cam && nearCorner(cam)) {
      id = '__cam'
      mode = 'scale'
    } else if (selPanel && nearCorner(selPanel)) {
      id = selected
      mode = 'scale'
    } else {
      id =
        hits.find((b) => px >= b.x && px <= b.x + b.w && py >= b.y && py <= b.y + b.h)?.id ?? null
      if (!id && inside(cam)) id = '__cam'
      else if (!id && inside(camPanel)) id = '__panel'
      else if (!id && inside(p.game)) id = '__game'
    }
    setSelected(id)
    if (!id) return
    ev.currentTarget.setPointerCapture(ev.pointerId)
    if (isPanel(id)) {
      const q = p[PANEL_KEY[id]]!
      drag.current = { id, mode, px, py, x: 0, y: 0, s: 0, cx: 0, cy: 0, rect: { ...q } }
    } else if (id === '__cam') {
      const cr = scene.regions.cam
      drag.current = { id, mode, px, py, x: cr.x, y: cr.y, s: cr.size, cx: cr.x * W, cy: cr.y * H }
    } else {
      const l = scene.layers.find((x) => x.id === id)!
      drag.current = {
        id,
        mode,
        px,
        py,
        x: l.x,
        y: l.y,
        s: l.kind === 'image' ? l.width : l.scale,
        cx: l.x * W,
        cy: l.y * H,
      }
    }
  }
  const onMove = (ev: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d) return
    const [px, py] = toScene(ev)
    if (isPanel(d.id) && d.rect) {
      const q = d.rect
      const r =
        d.mode === 'move'
          ? snapRect({ ...q, x: q.x + px - d.px, y: q.y + py - d.py }, W, H)
          : {
              ...q,
              w: Math.max(0.1 * W, q.w + px - d.px),
              h: Math.max(0.1 * H, q.h + py - d.py),
            }
      placePanel(PANEL_KEY[d.id], r, true)
      return
    }
    if (d.mode === 'move') {
      const x = d.x + (px - d.px) / W
      const y = d.y + (py - d.py) / H
      if (d.id === '__cam')
        hist.set(
          (s) => ({
            ...s,
            regions: {
              ...s.regions,
              cam: { ...s.regions.cam, x: clamp(x, 0, 1), y: clamp(y, 0, 1) },
            },
          }),
          true,
        )
      else setLayer(edit, d.id, { x: clamp(x, -0.2, 1.2), y: clamp(y, -0.2, 1.2) }, true)
    } else {
      const ratio =
        Math.hypot(px - d.cx, py - d.cy) / Math.max(10, Math.hypot(d.px - d.cx, d.py - d.cy))
      const s = d.s * ratio
      if (d.id === '__cam')
        hist.set(
          (sc) => ({
            ...sc,
            regions: { ...sc.regions, cam: { ...sc.regions.cam, size: clamp(s, 0.15, 0.7) } },
          }),
          true,
        )
      else {
        const l = scene.layers.find((x) => x.id === d.id)
        if (l?.kind === 'image') setLayer(edit, d.id, { width: clamp(s, 0.03, 1) }, true)
        else setLayer(edit, d.id, { scale: clamp(s, 0.2, 4) }, true)
      }
    }
  }
  const onUp = () => {
    if (drag.current) hist.commit()
    drag.current = null
  }

  const [switchNote, setSwitchNote] = useState<string | null>(null)
  const doSwitch = (tpl: TemplateChoice) =>
    switchTpl.mutate(
      { template: tpl, scene },
      {
        onSuccess: (s) => {
          hist.set(s)
          const wanted = templates.find((x) => x.id === tpl)
          setSwitchNote(s.template !== tpl && wanted ? t('cz.noCam', { name: wanted.name }) : null)
        },
      },
    )

  const rendering = short.status === 'rendering'
  const doRender = () => render.mutate({ scene, origin: 'manual_edit' })
  const tplInfo = templates.find((x) => x.id === scene.template)

  return (
    <div className="space-y-4">
      {/* template strip */}
      <Card className="p-3">
        <TemplatePicker value={scene.template} onChange={doSwitch} templates={templates} compact />
      </Card>

      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            hist.undo()
            setSwitchNote(null)
          }}
          disabled={!hist.canUndo}
          aria-label={t('cz.undo')}
          title={`${t('cz.undo')} (Ctrl+Z)`}
        >
          <Undo2 size={15} aria-hidden />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={hist.redo}
          disabled={!hist.canRedo}
          aria-label={t('cz.redo')}
          title={`${t('cz.redo')} (Ctrl+Shift+Z)`}
        >
          <Redo2 size={15} aria-hidden />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => doSwitch(scene.template)}
          title={t('cz.resetTplHelp')}
        >
          <RotateCcw size={14} aria-hidden /> {t('cz.resetTpl')}
        </Button>
        {dirty && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              hist.set(saved)
              setSwitchNote(null)
            }}
          >
            {t('cz.revert')}
          </Button>
        )}
        {(switchNote ?? data.note) && (
          <span className="text-xs text-warn">{switchNote ?? data.note}</span>
        )}
        <div className="flex-1" />
        {dirty ? (
          <Badge tone="info">{t('cz.unsaved')}</Badge>
        ) : (
          <Badge tone="ok">{t('cz.saved')}</Badge>
        )}
        <RenderProgress short={short} />
        <Button onClick={doRender} disabled={rendering || render.isPending}>
          {rendering || render.isPending ? (
            <Loader2 size={15} className="animate-spin" aria-hidden />
          ) : (
            <Clapperboard size={15} aria-hidden />
          )}
          {t('cz.render')}
        </Button>
      </div>
      {render.error && <p className="text-sm text-danger">{render.error.message}</p>}

      <div className="grid gap-4 md:grid-cols-[19rem_minmax(0,1fr)] 2xl:grid-cols-[18rem_minmax(0,1fr)_20rem]">
        {/* left: panels */}
        <Card className="order-2 max-h-[80vh] overflow-y-auto md:order-1">
          <div className="sticky top-0 z-10 flex border-b border-border bg-surface" role="tablist">
            {TABS.map(({ id, icon: Icon }) => (
              <button
                key={id}
                role="tab"
                aria-selected={tab === id}
                title={t(`cz.tabs.${id}`)}
                onClick={() => setTab(id)}
                className={cn(
                  'flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-medium transition',
                  tab === id ? 'text-accent' : 'text-muted hover:text-fg',
                )}
              >
                <Icon size={16} aria-hidden />
                {t(`cz.tabs.${id}`)}
              </button>
            ))}
          </div>
          {/* medium screens: the selected element's settings sit on top of the panel */}
          {layer && !wide && (
            <div className="border-b-4 border-accent/20">
              <div className="flex items-center justify-between px-4 pt-3 text-[11px] text-accent">
                <span className="font-semibold tracking-wider uppercase">{t('cz.selected')}</span>
                <button type="button" onClick={() => setSelected(null)} className="hover:underline">
                  {t('cz.done')}
                </button>
              </div>
              <Inspector e={edit} layer={layer} />
            </div>
          )}
          {tab === 'template' && (
            <>
              {tplInfo && <p className="px-4 pt-3 text-xs text-muted">{tplInfo.description}</p>}
              <TemplatePanel e={edit} />
            </>
          )}
          {tab === 'elements' && <ElementsPanel e={edit} />}
          {tab === 'add' && <AddPanel e={edit} />}
          {tab === 'captions' && <CaptionsPanel e={edit} />}
          {tab === 'effects' && <EffectsPanel e={edit} />}
        </Card>

        {/* centre: preview */}
        <div className="order-1 flex flex-col items-center gap-3 md:order-2">
          <Segmented
            label={t('cz.view')}
            value={view}
            onChange={(v) => {
              videoRef.current?.pause()
              setPlaying(false)
              setView(v)
            }}
            options={[
              { id: 'live', label: t('cz.viewLive') },
              {
                id: 'rendered',
                label: t('cz.viewRendered', { n: short.active?.version_no ?? '–' }),
              },
            ]}
          />
          <div
            className="relative max-w-full overflow-hidden rounded-2xl bg-black shadow-2xl ring-1 ring-border"
            style={previewBox(scene.canvas?.w ?? W, scene.canvas?.h ?? H)}
            data-testid="preview-box"
          >
            <video
              ref={videoRef}
              src={mediaUrl(cut.preview_asset_id)}
              preload="auto"
              playsInline
              muted={muted}
              onLoadedData={draw}
              onSeeked={draw}
              onEnded={() => setPlaying(false)}
              className="hidden"
            />
            {cut.matte_asset_id && (
              <video
                ref={matteRef}
                src={mediaUrl(cut.matte_asset_id)}
                preload="auto"
                playsInline
                muted
                onLoadedData={draw}
                onSeeked={draw}
                className="hidden"
                aria-hidden
              />
            )}
            <canvas
              ref={canvasRef}
              className={cn('size-full', view !== 'live' && 'hidden')}
              aria-label={t('cz.canvas')}
            />
            {view === 'live' && (
              <div
                className="absolute inset-0 cursor-crosshair touch-none"
                onPointerDown={onDown}
                onPointerMove={onMove}
                onPointerUp={onUp}
                onPointerCancel={onUp}
                data-testid="canvas-hit"
              >
                <div
                  ref={selRef}
                  className="pointer-events-none absolute hidden rounded-sm border-2 border-dashed border-accent shadow-[0_0_0_1px_rgba(0,0,0,0.4)]"
                >
                  <span className="absolute -right-2 -bottom-2 size-4 rounded-full border-2 border-white bg-accent" />
                </div>
              </div>
            )}
            {view === 'rendered' && short.active?.mp4_asset_id && (
              <video
                key={short.active.id}
                controls
                playsInline
                src={mediaUrl(short.active.mp4_asset_id)}
                className="absolute inset-0 size-full bg-black object-contain"
                aria-label={t('render.player')}
              />
            )}
          </div>
          {view === 'live' && (
            <div className="flex w-full max-w-[28rem] items-center gap-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={togglePlay}
                aria-label={playing ? t('cz.pause') : t('cz.play')}
              >
                {playing ? <Pause size={15} /> : <Play size={15} />}
              </Button>
              <div className="relative flex-1">
                <input
                  type="range"
                  aria-label={t('cz.time')}
                  min={0}
                  max={duration}
                  step={0.01}
                  value={time}
                  onChange={(e) => seek(Number(e.target.value))}
                  className="w-full cursor-pointer accent-accent"
                />
                {scene.effects.moments.map((m, i) => (
                  <span
                    key={i}
                    className="pointer-events-none absolute -top-1 size-1.5 rounded-full bg-warn"
                    style={{ left: `${(m / duration) * 100}%` }}
                    aria-hidden
                  />
                ))}
              </div>
              <span className="w-20 text-right text-xs text-muted tabular-nums">
                {formatClock(time)} / {formatClock(duration)}
              </span>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setMuted((m) => !m)}
                aria-label={muted ? t('cz.unmute') : t('cz.mute')}
              >
                {muted ? <VolumeX size={15} /> : <Volume2 size={15} />}
              </Button>
            </div>
          )}
          <p className="text-center text-[11px] text-muted">{t('cz.hint')}</p>
        </div>

        {/* right: inspector */}
        {wide && (
          <Card className="order-3 max-h-[80vh] overflow-y-auto">
            {layer ? (
              <Inspector e={edit} layer={layer} />
            ) : selected === '__cam' ? (
              <div className="p-4 text-xs text-muted">{t('cz.camSelected')}</div>
            ) : (
              <div className="space-y-3 p-4 text-xs text-muted">
                <p className="font-medium text-fg">{t('cz.tips.title')}</p>
                <ul className="list-disc space-y-1.5 pl-4">
                  {(['click', 'drag', 'corner', 'add', 'keys', 'render'] as const).map((k) => (
                    <li key={k}>{t(`cz.tips.${k}`)}</li>
                  ))}
                </ul>
              </div>
            )}
          </Card>
        )}
      </div>
    </div>
  )
}

function clamp(v: number, a: number, b: number) {
  return Math.min(b, Math.max(a, v))
}

/** Room for a third column (inspector) next to the panels and the preview. */
function useWide(): boolean {
  const query = '(min-width: 1536px)'
  const [wide, setWide] = useState(() => globalThis.matchMedia?.(query).matches ?? false)
  useEffect(() => {
    const m = globalThis.matchMedia?.(query)
    if (!m) return
    const on = () => setWide(m.matches)
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [])
  return wide
}
