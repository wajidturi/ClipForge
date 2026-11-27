/** Side panels of the customisation studio. All edits go through `Edit` (undo-able). */
import {
  ArrowDown,
  ArrowUp,
  Copy,
  Eye,
  EyeOff,
  ImagePlus,
  Loader2,
  Plus,
  Sparkles,
  Trash2,
  Type,
  X,
} from 'lucide-react'
import { useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui'
import { mediaUrl, type Layer, type Regions } from '@/lib/api/client'
import { useDeleteImage, useImages, useUploadImage } from '@/lib/studio'
import { cn, formatClock } from '@/lib/utils'
import { ColorField, Row, Section, Segmented, Select, Slider, Toggle } from './controls'
import {
  addLayer,
  removeLayer,
  setCaptions,
  setCam,
  setDivider,
  setEffects,
  setFrame,
  setLayer,
  setRegions,
  type Edit,
} from './edit'
import { EMOJIS, PLACEHOLDERS, STICKERS, newLayer } from './library'

const pct = (v: number) => `${Math.round(v * 100)}%`
const secs = (v: number) => `${v.toFixed(1)}s`

function useLayerName() {
  const { t } = useTranslation()
  return (l: Layer) =>
    l.name ||
    (l.role ? t(`cz.role.${l.role}`, { defaultValue: '' }) : '') ||
    (l.kind === 'image' ? t('cz.role.logo') : l.text.slice(0, 24) || t('cz.role.user'))
}

const SWATCH: Record<string, string> = {
  original: 'linear-gradient(135deg,#6b7280,#9ca3af)',
  blur_soft: 'radial-gradient(circle at 50% 40%,#d1d5db,#6b7280)',
  blur_strong: 'radial-gradient(circle at 50% 40%,#9ca3af,#374151)',
}

/** Small preview of a facecam background (pictures come from the renderer). */
function BgSwatch({ id }: { id: string }) {
  const pic = !(id in SWATCH)
  return (
    <span
      className="block h-8 w-full rounded-sm bg-cover bg-center"
      style={{
        backgroundImage: pic ? `url(/api/v1/render/backgrounds/${id}.png?w=96&h=64)` : SWATCH[id],
        filter: id.startsWith('blur') ? 'blur(1px)' : undefined,
      }}
    />
  )
}

// ------------------------------------------------------------------ template
export function TemplatePanel({ e }: { e: Edit }) {
  const { t } = useTranslation()
  const s = e.scene
  const r = s.regions
  const stacked = ['streamer_first', 'gameplay_first', 'dual_vision'].includes(s.template)
  const name = useLayerName()
  const elements = s.layers.filter((l) => l.role && !['user', 'logo'].includes(l.role))
  return (
    <>
      {stacked && (
        <Section title={t('cz.tpl.layout')}>
          <Row label={t(`cz.tpl.split.${s.template}`)}>
            <Slider
              label={t(`cz.tpl.split.${s.template}`)}
              value={r.split}
              min={0.25}
              max={0.75}
              step={0.01}
              format={pct}
              onChange={(v) => setRegions(e, { split: v }, true)}
              onCommit={e.commit}
            />
          </Row>
        </Section>
      )}
      {s.template === 'floating_facecam' && (
        <Section
          title={t('cz.tpl.cam')}
          action={
            <Toggle
              label={t('cz.tpl.camShow')}
              checked={r.cam.visible}
              onChange={(v) => setCam(e, { visible: v })}
            />
          }
        >
          <p className="text-[11px] text-muted">{t('cz.tpl.camDrag')}</p>
          <Row label={t('cz.tpl.size')}>
            <Slider
              label={t('cz.tpl.size')}
              value={r.cam.size}
              min={0.15}
              max={0.7}
              step={0.01}
              format={pct}
              onChange={(v) => setCam(e, { size: v }, true)}
              onCommit={e.commit}
            />
          </Row>
          <Row label={t('cz.tpl.shape')}>
            <Segmented
              label={t('cz.tpl.shape')}
              value={r.cam.shape}
              options={(['circle', 'rounded', 'square'] as const).map((id) => ({
                id,
                label: t(`cz.shape.${id}`),
              }))}
              onChange={(v) => setCam(e, { shape: v })}
            />
          </Row>
          <Row label={t('cz.tpl.border')}>
            <ColorField
              label={t('cz.tpl.border')}
              value={r.cam.border_color}
              onChange={(v) => setCam(e, { border_color: v })}
            />
          </Row>
          <Row label={t('cz.tpl.borderWidth')}>
            <Slider
              label={t('cz.tpl.borderWidth')}
              value={r.cam.border_width}
              min={0}
              max={24}
              onChange={(v) => setCam(e, { border_width: v }, true)}
              onCommit={e.commit}
            />
          </Row>
          <Row label={t('cz.tpl.glow')}>
            <Slider
              label={t('cz.tpl.glow')}
              value={r.cam.glow}
              min={0}
              max={40}
              onChange={(v) => setCam(e, { glow: v }, true)}
              onCommit={e.commit}
            />
          </Row>
        </Section>
      )}
      {(stacked || s.template === 'floating_facecam') && (
        <Section title={t('cz.tpl.camLook')}>
          {e.cutOut ? (
            <div
              className="grid grid-cols-4 gap-1.5"
              role="radiogroup"
              aria-label={t('cz.tpl.camBg')}
            >
              {e.backgrounds.map((b) => (
                <button
                  key={b.id}
                  type="button"
                  role="radio"
                  aria-checked={r.cam_bg === b.id}
                  title={b.label}
                  onClick={() => setRegions(e, { cam_bg: b.id as Regions['cam_bg'] })}
                  className={cn(
                    'flex flex-col items-center gap-1 rounded-md border p-1 text-[10px] leading-tight transition',
                    r.cam_bg === b.id
                      ? 'border-accent bg-accent/10'
                      : 'border-border hover:bg-surface-2',
                  )}
                >
                  <BgSwatch id={b.id} />
                  <span className="w-full truncate text-center">{b.label}</span>
                </button>
              ))}
            </div>
          ) : (
            <p className="text-[11px] text-muted">{t('cz.tpl.camBgNone')}</p>
          )}
          <Row label={t('cz.tpl.camEnhance')}>
            <Toggle
              label={t('cz.tpl.camEnhance')}
              checked={r.cam_enhance}
              onChange={(v) => setRegions(e, { cam_enhance: v })}
            />
          </Row>
          <p className="text-[11px] text-muted">{t('cz.tpl.camEnhanceHelp')}</p>
        </Section>
      )}
      {s.template === 'dual_vision' && (
        <Section title={t('cz.tpl.divider')}>
          <Row label={t('cz.tpl.style')}>
            <Segmented
              label={t('cz.tpl.style')}
              value={r.divider.style}
              options={(['ribbon', 'bar', 'line', 'none'] as const).map((id) => ({
                id,
                label: t(`cz.divider.${id}`),
              }))}
              onChange={(v) => setDivider(e, { style: v })}
            />
          </Row>
          <Row label={t('cz.colors')}>
            <ColorField
              label={t('cz.color1')}
              value={r.divider.color}
              onChange={(v) => setDivider(e, { color: v })}
            />
            <ColorField
              label={t('cz.color2')}
              value={r.divider.color2}
              onChange={(v) => setDivider(e, { color2: v })}
            />
          </Row>
          <Row label={t('cz.tpl.thickness')}>
            <Slider
              label={t('cz.tpl.thickness')}
              value={r.divider.thickness}
              min={4}
              max={160}
              onChange={(v) => setDivider(e, { thickness: v }, true)}
              onCommit={e.commit}
            />
          </Row>
          <Row label={t('cz.tpl.tilt')}>
            <Slider
              label={t('cz.tpl.tilt')}
              value={r.divider.tilt}
              min={-12}
              max={12}
              step={0.5}
              format={(v) => `${v}°`}
              onChange={(v) => setDivider(e, { tilt: v }, true)}
              onCommit={e.commit}
            />
          </Row>
        </Section>
      )}
      {(s.template === 'floating_facecam' || s.template === 'cinematic') && (
        <Section title={t('cz.tpl.picture')}>
          <Row label={t('cz.tpl.fit')}>
            <Segmented
              label={t('cz.tpl.fit')}
              value={r.fit}
              options={(['fill', 'blur'] as const).map((id) => ({ id, label: t(`cz.fit.${id}`) }))}
              onChange={(v) => setRegions(e, { fit: v })}
            />
          </Row>
        </Section>
      )}
      <Section title={t('cz.tpl.frame')}>
        <Row label={t('cz.tpl.style')}>
          <Segmented
            label={t('cz.tpl.style')}
            value={r.frame.style}
            options={(['neon', 'solid', 'none'] as const).map((id) => ({
              id,
              label: t(`cz.frame.${id}`),
            }))}
            onChange={(v) => setFrame(e, { style: v })}
          />
        </Row>
        {r.frame.style !== 'none' && (
          <>
            <Row label={t('cz.colors')}>
              <ColorField
                label={t('cz.color1')}
                value={r.frame.color}
                onChange={(v) => setFrame(e, { color: v })}
              />
              <ColorField
                label={t('cz.color2')}
                value={r.frame.color2}
                onChange={(v) => setFrame(e, { color2: v })}
              />
            </Row>
            <Row label={t('cz.tpl.borderWidth')}>
              <Slider
                label={t('cz.tpl.borderWidth')}
                value={r.frame.width}
                min={0}
                max={20}
                onChange={(v) => setFrame(e, { width: v }, true)}
                onCommit={e.commit}
              />
            </Row>
            {r.frame.style === 'neon' && (
              <Row label={t('cz.tpl.glow')}>
                <Slider
                  label={t('cz.tpl.glow')}
                  value={r.frame.glow}
                  min={0}
                  max={40}
                  onChange={(v) => setFrame(e, { glow: v }, true)}
                  onCommit={e.commit}
                />
              </Row>
            )}
            <Row label={t('cz.tpl.radius')}>
              <Slider
                label={t('cz.tpl.radius')}
                value={r.frame.radius}
                min={0}
                max={80}
                onChange={(v) => setFrame(e, { radius: v }, true)}
                onCommit={e.commit}
              />
            </Row>
            <Row label={t('cz.tpl.gap')}>
              <Slider
                label={t('cz.tpl.gap')}
                value={r.frame.gap}
                min={0}
                max={48}
                onChange={(v) => setFrame(e, { gap: v }, true)}
                onCommit={e.commit}
              />
            </Row>
            <Row label={t('cz.tpl.background')}>
              <ColorField
                label={t('cz.tpl.background')}
                value={r.frame.background}
                onChange={(v) => setFrame(e, { background: v })}
              />
            </Row>
          </>
        )}
      </Section>
      {elements.length > 0 && (
        <Section title={t('cz.tpl.elements')}>
          <ul className="space-y-2">
            {elements.map((l) => (
              <li key={l.id} className="space-y-1">
                <div className="flex items-center gap-2 text-xs">
                  <button
                    type="button"
                    onClick={() => setLayer(e, l.id, { visible: !l.visible })}
                    aria-label={l.visible ? t('cz.hide') : t('cz.show')}
                    className="text-muted hover:text-fg"
                  >
                    {l.visible ? <Eye size={14} /> : <EyeOff size={14} />}
                  </button>
                  <button
                    type="button"
                    onClick={() => e.select(l.id)}
                    className="flex-1 text-left font-medium hover:text-accent"
                  >
                    {name(l)}
                  </button>
                </div>
                {l.kind === 'text' && (
                  <input
                    value={l.text}
                    aria-label={name(l)}
                    onChange={(ev) => setLayer(e, l.id, { text: ev.target.value }, true)}
                    onBlur={e.commit}
                    className="h-8 w-full rounded-md border border-border bg-surface-2 px-2 text-xs"
                  />
                )}
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-muted">{t('cz.tpl.placeholderHelp')}</p>
        </Section>
      )}
    </>
  )
}

// ------------------------------------------------------------------ elements
export function ElementsPanel({ e }: { e: Edit }) {
  const { t } = useTranslation()
  const name = useLayerName()
  const layers = [...e.scene.layers].reverse() // top-most first
  return (
    <Section title={t('cz.elements.title', { n: layers.length })}>
      {!layers.length && <p className="text-xs text-muted">{t('cz.elements.empty')}</p>}
      <ul className="space-y-1">
        {layers.map((l) => (
          <li
            key={l.id}
            className={cn(
              'flex items-center gap-2 rounded-md px-2 py-1.5 text-xs',
              e.selected === l.id ? 'bg-accent/12 text-accent' : 'hover:bg-surface-2',
            )}
          >
            <button
              type="button"
              onClick={() => setLayer(e, l.id, { visible: !l.visible })}
              aria-label={l.visible ? t('cz.hide') : t('cz.show')}
              className="text-muted hover:text-fg"
            >
              {l.visible ? <Eye size={14} /> : <EyeOff size={14} />}
            </button>
            <button
              type="button"
              onClick={() => e.select(l.id)}
              className={cn('min-w-0 flex-1 truncate text-left', !l.visible && 'opacity-50')}
            >
              {l.kind === 'image' ? '🖼 ' : l.kind === 'emoji' ? '' : 'T  '}
              {name(l)}
            </button>
            <span className="text-[10px] text-muted tabular-nums">
              {secs(l.start)}–{l.end == null ? t('cz.end') : secs(l.end)}
            </span>
          </li>
        ))}
      </ul>
    </Section>
  )
}

// ------------------------------------------------------------------ add
export function AddPanel({ e }: { e: Edit }) {
  const { t } = useTranslation()
  const images = useImages()
  const upload = useUploadImage()
  const del = useDeleteImage()
  const fileRef = useRef<HTMLInputElement>(null)
  const addLogo = (id: string) =>
    addLayer(
      e,
      newLayer({
        kind: 'image',
        role: 'logo',
        asset_id: id,
        x: 0.86,
        y: 0.06,
        width: 0.2,
        opacity: 0.95,
        anim_in: 'fade',
        anim_out: 'none',
      }),
    )
  return (
    <>
      <Section title={t('cz.add.text')}>
        <div className="grid grid-cols-2 gap-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => addLayer(e, newLayer({ text: t('cz.add.newText'), y: 0.3 }))}
          >
            <Type size={14} aria-hidden /> {t('cz.add.headline')}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() =>
              addLayer(
                e,
                newLayer({
                  text: t('cz.add.newSmall'),
                  font: 'segoe_black',
                  size: 48,
                  stroke: 0,
                  shape: 'pill',
                  shape_color: '#111111',
                  y: 0.4,
                  upper: false,
                }),
              )
            }
          >
            <Plus size={14} aria-hidden /> {t('cz.add.label')}
          </Button>
        </div>
      </Section>
      <Section title={t('cz.add.logo')}>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          className="hidden"
          onChange={(ev) => {
            const f = ev.target.files?.[0]
            if (f) upload.mutate(f, { onSuccess: (img) => addLogo(img.id) })
            ev.target.value = ''
          }}
        />
        <Button size="sm" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? (
            <Loader2 size={14} className="animate-spin" aria-hidden />
          ) : (
            <ImagePlus size={14} aria-hidden />
          )}
          {t('cz.add.upload')}
        </Button>
        {upload.error && <p className="text-xs text-danger">{upload.error.message}</p>}
        {(images.data?.length ?? 0) > 0 && (
          <div className="grid grid-cols-4 gap-2">
            {images.data!.map((img) => (
              <div key={img.id} className="group relative">
                <button
                  type="button"
                  onClick={() => addLogo(img.id)}
                  title={img.name ?? ''}
                  className="flex aspect-square w-full items-center justify-center rounded-md border border-border bg-[repeating-conic-gradient(#8882_0_25%,transparent_0_50%)] bg-[length:12px_12px] p-1 hover:border-accent"
                >
                  <img
                    src={mediaUrl(img.id)}
                    alt={img.name ?? ''}
                    className="max-h-full max-w-full object-contain"
                  />
                </button>
                <button
                  type="button"
                  onClick={() => del.mutate(img.id)}
                  aria-label={t('cz.add.deleteImage')}
                  className="absolute -top-1.5 -right-1.5 hidden rounded-full bg-danger p-0.5 text-white group-hover:block"
                >
                  <X size={10} />
                </button>
              </div>
            ))}
          </div>
        )}
      </Section>
      <Section title={t('cz.add.stickers')}>
        <div className="grid grid-cols-2 gap-1.5">
          {STICKERS.map((st) => (
            <button
              key={st.id}
              type="button"
              onClick={() =>
                addLayer(
                  e,
                  newLayer({
                    ...st.layer,
                    start: e.time,
                    end: Math.min(e.duration, e.time + 3),
                    y: 0.35,
                  }),
                )
              }
              className="truncate rounded-md border border-border px-2 py-1.5 text-[11px] font-bold tracking-wide hover:border-accent hover:bg-accent/8"
              style={{
                color: st.layer.color && st.layer.shape === 'none' ? st.layer.color : undefined,
              }}
            >
              {st.label}
            </button>
          ))}
        </div>
        <p className="text-[11px] text-muted">{t('cz.add.stickerHelp')}</p>
      </Section>
      <Section title={t('cz.add.emoji')}>
        <div className="grid grid-cols-8 gap-1">
          {EMOJIS.map((em) => (
            <button
              key={em}
              type="button"
              onClick={() =>
                addLayer(
                  e,
                  newLayer({
                    kind: 'emoji',
                    text: em,
                    font: 'emoji',
                    size: 150,
                    stroke: 0,
                    shadow: false,
                    x: 0.75,
                    y: 0.3,
                    start: e.time,
                    end: Math.min(e.duration, e.time + 2.5),
                  }),
                )
              }
              className="rounded-md p-1 text-xl hover:bg-surface-2"
              aria-label={em}
            >
              {em}
            </button>
          ))}
        </div>
      </Section>
    </>
  )
}

// ------------------------------------------------------------------ captions
export function CaptionsPanel({ e }: { e: Edit }) {
  const { t } = useTranslation()
  const c = e.scene.captions
  const fontOpts = e.fonts
    .filter((f) => f.id !== 'emoji')
    .map((f) => ({ id: f.id, label: f.label }))
  return (
    <>
      <Section
        title={t('cz.cap.title')}
        action={
          <Toggle
            label={t('cz.cap.show')}
            checked={c.visible}
            onChange={(v) => setCaptions(e, { visible: v })}
          />
        }
      >
        <div className="grid grid-cols-3 gap-1.5">
          {Object.entries(e.presets).map(([id, p]) => (
            <button
              key={id}
              type="button"
              onClick={() => setCaptions(e, { ...p, y: c.y, visible: c.visible })}
              className={cn(
                'rounded-md border px-2 py-1.5 text-[11px] font-semibold capitalize',
                c.preset === id
                  ? 'border-accent bg-accent/10 text-accent'
                  : 'border-border hover:bg-surface-2',
              )}
            >
              {t(`cz.cap.preset.${id}`, { defaultValue: id })}
            </button>
          ))}
        </div>
      </Section>
      <Section title={t('cz.cap.text')}>
        <Row label={t('cz.font')}>
          <Select
            label={t('cz.font')}
            value={c.font}
            options={fontOpts}
            onChange={(v) => setCaptions(e, { font: v })}
          />
        </Row>
        <Row label={t('cz.size')}>
          <Slider
            label={t('cz.size')}
            value={c.size}
            min={28}
            max={180}
            onChange={(v) => setCaptions(e, { size: v }, true)}
            onCommit={e.commit}
          />
        </Row>
        <Row label={t('cz.cap.position')}>
          <Slider
            label={t('cz.cap.position')}
            value={c.y}
            min={0.08}
            max={0.95}
            step={0.01}
            format={pct}
            onChange={(v) => setCaptions(e, { y: v }, true)}
            onCommit={e.commit}
          />
        </Row>
        <Row label={t('cz.cap.words')}>
          <Slider
            label={t('cz.cap.words')}
            value={c.words}
            min={1}
            max={6}
            onChange={(v) => setCaptions(e, { words: v }, true)}
            onCommit={e.commit}
          />
        </Row>
        <Row label={t('cz.cap.mode')}>
          <Select
            label={t('cz.cap.mode')}
            value={c.mode}
            options={(['highlight', 'single', 'karaoke', 'plain'] as const).map((id) => ({
              id,
              label: t(`cz.cap.modes.${id}`),
            }))}
            onChange={(v) => setCaptions(e, { mode: v })}
          />
        </Row>
        <Row label={t('cz.cap.upper')}>
          <Toggle
            label={t('cz.cap.upper')}
            checked={c.upper}
            onChange={(v) => setCaptions(e, { upper: v })}
          />
        </Row>
        <Row label={t('cz.cap.pop')}>
          <Toggle
            label={t('cz.cap.pop')}
            checked={c.animation === 'pop'}
            onChange={(v) => setCaptions(e, { animation: v ? 'pop' : 'none' })}
          />
        </Row>
      </Section>
      <Section title={t('cz.colors')}>
        <Row label={t('cz.cap.color')}>
          <ColorField
            label={t('cz.cap.color')}
            value={c.color}
            onChange={(v) => setCaptions(e, { color: v })}
          />
        </Row>
        <Row label={t('cz.cap.highlight')}>
          <ColorField
            label={t('cz.cap.highlight')}
            value={c.highlight}
            onChange={(v) => setCaptions(e, { highlight: v })}
          />
        </Row>
        <Row label={t('cz.cap.keyword')}>
          <ColorField
            label={t('cz.cap.keyword')}
            value={c.keyword}
            onChange={(v) => setCaptions(e, { keyword: v })}
          />
        </Row>
        <Row label={t('cz.cap.outline')}>
          <ColorField
            label={t('cz.cap.outline')}
            value={c.outline_color}
            onChange={(v) => setCaptions(e, { outline_color: v })}
          />
          <Slider
            label={t('cz.cap.outlineWidth')}
            value={c.outline}
            min={0}
            max={20}
            onChange={(v) => setCaptions(e, { outline: v }, true)}
            onCommit={e.commit}
          />
        </Row>
        <Row label={t('cz.cap.box')}>
          <Toggle
            label={t('cz.cap.box')}
            checked={c.box != null}
            onChange={(v) => setCaptions(e, { box: v ? '#7C5CFF' : null })}
          />
          {c.box != null && (
            <ColorField
              label={t('cz.cap.box')}
              value={c.box}
              onChange={(v) => setCaptions(e, { box: v })}
            />
          )}
        </Row>
        <p className="text-[11px] text-muted">{t('cz.cap.fixHelp')}</p>
      </Section>
    </>
  )
}

// ------------------------------------------------------------------ effects
export function EffectsPanel({ e }: { e: Edit }) {
  const { t } = useTranslation()
  const fx = e.scene.effects
  const toggles = ['shake', 'flash', 'glitch', 'speed_lines', 'vignette', 'letterbox'] as const
  return (
    <>
      <Section
        title={t('cz.fx.zoom')}
        action={
          <Toggle
            label={t('cz.fx.zoom')}
            checked={fx.zoom_punch}
            onChange={(v) => setEffects(e, { zoom_punch: v })}
          />
        }
      >
        {fx.zoom_punch && (
          <Row label={t('cz.fx.amount')}>
            <Slider
              label={t('cz.fx.amount')}
              value={fx.zoom_amount}
              min={0.02}
              max={0.25}
              step={0.01}
              format={pct}
              onChange={(v) => setEffects(e, { zoom_amount: v }, true)}
              onCommit={e.commit}
            />
          </Row>
        )}
        <p className="text-[11px] text-muted">{t('cz.fx.zoomHelp')}</p>
      </Section>
      <Section title={t('cz.fx.moments')}>
        <ul className="space-y-2">
          {toggles.map((k) => (
            <li key={k} className="flex items-center justify-between gap-2 text-xs">
              <span>{t(`cz.fx.${k}`)}</span>
              <Toggle
                label={t(`cz.fx.${k}`)}
                checked={fx[k]}
                onChange={(v) => setEffects(e, { [k]: v })}
              />
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap gap-1.5">
          {fx.moments.map((m, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 rounded-full bg-accent/12 px-2 py-0.5 text-[11px] text-accent tabular-nums"
            >
              <Sparkles size={10} aria-hidden /> {formatClock(m)} ({m.toFixed(1)}s)
              <button
                type="button"
                aria-label={t('cz.remove')}
                onClick={() => setEffects(e, { moments: fx.moments.filter((_, j) => j !== i) })}
              >
                <X size={10} />
              </button>
            </span>
          ))}
        </div>
        <Button
          size="sm"
          variant="secondary"
          disabled={fx.moments.length >= 12}
          onClick={() =>
            setEffects(e, {
              moments: [...fx.moments, Math.round(e.time * 100) / 100].sort((a, b) => a - b),
            })
          }
        >
          <Plus size={14} aria-hidden /> {t('cz.fx.addMoment', { t: e.time.toFixed(1) })}
        </Button>
      </Section>
      <Section title={t('cz.fx.color')}>
        <Segmented
          label={t('cz.fx.color')}
          value={fx.color}
          options={(['none', 'vivid', 'hdr', 'cinematic'] as const).map((id) => ({
            id,
            label: t(`cz.fx.grade.${id}`),
          }))}
          onChange={(v) => setEffects(e, { color: v })}
        />
      </Section>
    </>
  )
}

// ------------------------------------------------------------------ inspector
export function Inspector({ e, layer }: { e: Edit; layer: Layer }) {
  const { t } = useTranslation()
  const name = useLayerName()
  const up = (patch: Partial<Layer>, transient = false) => setLayer(e, layer.id, patch, transient)
  const fontOpts = e.fonts
    .filter((f) => f.id !== 'emoji')
    .map((f) => ({ id: f.id, label: f.label }))
  const move = (dir: 1 | -1) =>
    e.update((s) => {
      const i = s.layers.findIndex((l) => l.id === layer.id)
      const j = i + dir
      if (i < 0 || j < 0 || j >= s.layers.length) return s
      const layers = [...s.layers]
      ;[layers[i], layers[j]] = [layers[j]!, layers[i]!]
      return { ...s, layers }
    })
  const isText = layer.kind !== 'image'
  return (
    <>
      <Section
        title={name(layer)}
        action={
          <div className="flex gap-1">
            <button
              type="button"
              className="rounded p-1 text-muted hover:bg-surface-2 hover:text-fg"
              aria-label={layer.visible ? t('cz.hide') : t('cz.show')}
              onClick={() => up({ visible: !layer.visible })}
            >
              {layer.visible ? <Eye size={14} /> : <EyeOff size={14} />}
            </button>
            <button
              type="button"
              className="rounded p-1 text-muted hover:bg-surface-2 hover:text-fg"
              aria-label={t('cz.forward')}
              onClick={() => move(1)}
            >
              <ArrowUp size={14} />
            </button>
            <button
              type="button"
              className="rounded p-1 text-muted hover:bg-surface-2 hover:text-fg"
              aria-label={t('cz.backward')}
              onClick={() => move(-1)}
            >
              <ArrowDown size={14} />
            </button>
            <button
              type="button"
              className="rounded p-1 text-muted hover:bg-surface-2 hover:text-fg"
              aria-label={t('cz.duplicate')}
              onClick={() =>
                addLayer(e, {
                  ...layer,
                  id: Math.random().toString(16).slice(2, 12),
                  role: layer.role === 'logo' ? 'logo' : 'user',
                  x: Math.min(1, layer.x + 0.04),
                  y: Math.min(1, layer.y + 0.03),
                })
              }
            >
              <Copy size={14} />
            </button>
            <button
              type="button"
              className="rounded p-1 text-danger hover:bg-danger/10"
              aria-label={t('cz.delete')}
              onClick={() => removeLayer(e, layer.id)}
            >
              <Trash2 size={14} />
            </button>
          </div>
        }
      >
        {isText && (
          <>
            <textarea
              value={layer.text}
              aria-label={t('cz.text')}
              rows={2}
              maxLength={160}
              onChange={(ev) => up({ text: ev.target.value }, true)}
              onBlur={e.commit}
              className="w-full rounded-md border border-border bg-surface-2 px-2 py-1.5 text-sm"
            />
            {layer.kind === 'text' && (
              <div className="flex flex-wrap gap-1">
                {PLACEHOLDERS.map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => up({ text: `${layer.text} ${p}`.trim() })}
                    className="rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted hover:text-fg"
                  >
                    {p}
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </Section>
      {layer.kind === 'text' && (
        <Section title={t('cz.style')}>
          <Row label={t('cz.font')}>
            <Select
              label={t('cz.font')}
              value={layer.font}
              options={fontOpts}
              onChange={(v) => up({ font: v })}
            />
          </Row>
          <Row label={t('cz.size')}>
            <Slider
              label={t('cz.size')}
              value={layer.size}
              min={16}
              max={260}
              onChange={(v) => up({ size: v }, true)}
              onCommit={e.commit}
            />
          </Row>
          <Row label={t('cz.colors')}>
            <ColorField
              label={t('cz.textColor')}
              value={layer.color}
              onChange={(v) => up({ color: v })}
            />
            <ColorField
              label={t('cz.strokeColor')}
              value={layer.stroke_color}
              onChange={(v) => up({ stroke_color: v })}
            />
          </Row>
          <Row label={t('cz.stroke')}>
            <Slider
              label={t('cz.stroke')}
              value={layer.stroke}
              min={0}
              max={24}
              onChange={(v) => up({ stroke: v }, true)}
              onCommit={e.commit}
            />
          </Row>
          <Row label={t('cz.textStyle')}>
            <Segmented
              label={t('cz.textStyle')}
              value={`${layer.italic ? 'i' : ''}${layer.upper ? 'u' : ''}` || 'n'}
              options={[
                { id: 'n', label: 'Aa' },
                { id: 'u', label: 'AA' },
                { id: 'i', label: 'Aa ⁄' },
                { id: 'iu', label: 'AA ⁄' },
              ]}
              onChange={(v) => up({ italic: v.includes('i'), upper: v.includes('u') })}
            />
          </Row>
          <Row label={t('cz.shadow')}>
            <Toggle
              label={t('cz.shadow')}
              checked={layer.shadow}
              onChange={(v) => up({ shadow: v })}
            />
          </Row>
          <Row label={t('cz.shapeLabel')}>
            <Select
              label={t('cz.shapeLabel')}
              value={layer.shape}
              options={(['none', 'box', 'pill', 'tag', 'ribbon', 'burst'] as const).map((id) => ({
                id,
                label: t(`cz.shapes.${id}`),
              }))}
              onChange={(v) => up({ shape: v })}
            />
          </Row>
          {layer.shape !== 'none' && (
            <Row label={t('cz.shapeColors')}>
              <ColorField
                label={t('cz.shapeFill')}
                value={layer.shape_color}
                onChange={(v) => up({ shape_color: v })}
              />
              <Toggle
                label={t('cz.shapeOutline')}
                checked={layer.shape_stroke != null}
                onChange={(v) => up({ shape_stroke: v ? '#FFFFFF' : null })}
              />
              {layer.shape_stroke != null && (
                <ColorField
                  label={t('cz.shapeOutline')}
                  value={layer.shape_stroke}
                  onChange={(v) => up({ shape_stroke: v })}
                />
              )}
            </Row>
          )}
          <Row label={t('cz.wrap')}>
            <Slider
              label={t('cz.wrap')}
              value={layer.max_width}
              min={0.2}
              max={1}
              step={0.01}
              format={pct}
              onChange={(v) => up({ max_width: v }, true)}
              onCommit={e.commit}
            />
          </Row>
        </Section>
      )}
      <Section title={t('cz.placement')}>
        {layer.kind === 'image' ? (
          <Row label={t('cz.width')}>
            <Slider
              label={t('cz.width')}
              value={layer.width}
              min={0.03}
              max={1}
              step={0.01}
              format={pct}
              onChange={(v) => up({ width: v }, true)}
              onCommit={e.commit}
            />
          </Row>
        ) : (
          <Row label={t('cz.scale')}>
            <Slider
              label={t('cz.scale')}
              value={layer.scale}
              min={0.2}
              max={4}
              step={0.05}
              format={(v) => `${v.toFixed(2)}×`}
              onChange={(v) => up({ scale: v }, true)}
              onCommit={e.commit}
            />
          </Row>
        )}
        <Row label="X">
          <Slider
            label="X"
            value={layer.x}
            min={-0.2}
            max={1.2}
            step={0.005}
            format={pct}
            onChange={(v) => up({ x: v }, true)}
            onCommit={e.commit}
          />
        </Row>
        <Row label="Y">
          <Slider
            label="Y"
            value={layer.y}
            min={-0.2}
            max={1.2}
            step={0.005}
            format={pct}
            onChange={(v) => up({ y: v }, true)}
            onCommit={e.commit}
          />
        </Row>
        <Row label={t('cz.rotation')}>
          <Slider
            label={t('cz.rotation')}
            value={layer.rotation}
            min={-45}
            max={45}
            format={(v) => `${v}°`}
            onChange={(v) => up({ rotation: v }, true)}
            onCommit={e.commit}
          />
        </Row>
        <Row label={t('cz.opacity')}>
          <Slider
            label={t('cz.opacity')}
            value={layer.opacity}
            min={0}
            max={1}
            step={0.01}
            format={pct}
            onChange={(v) => up({ opacity: v }, true)}
            onCommit={e.commit}
          />
        </Row>
      </Section>
      <Section title={t('cz.timing')}>
        <Row label={t('cz.from')}>
          <Slider
            label={t('cz.from')}
            value={layer.start}
            min={0}
            max={Math.max(0.1, e.duration - 0.1)}
            step={0.05}
            format={secs}
            onChange={(v) => up({ start: v }, true)}
            onCommit={e.commit}
          />
        </Row>
        <Row label={t('cz.until')}>
          <Slider
            label={t('cz.until')}
            value={layer.end ?? e.duration}
            min={0.1}
            max={e.duration}
            step={0.05}
            format={secs}
            onChange={(v) => up({ end: v >= e.duration - 0.01 ? null : v }, true)}
            onCommit={e.commit}
          />
        </Row>
        <div className="flex flex-wrap gap-1.5">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => up({ start: Math.round(e.time * 100) / 100 })}
          >
            {t('cz.startNow')}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => up({ end: Math.max(layer.start + 0.2, Math.round(e.time * 100) / 100) })}
          >
            {t('cz.endNow')}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => up({ start: 0, end: null })}>
            {t('cz.wholeVideo')}
          </Button>
        </div>
      </Section>
      <Section title={t('cz.animation')}>
        <Row label={t('cz.animIn')}>
          <Select
            label={t('cz.animIn')}
            value={layer.anim_in}
            options={(
              [
                'none',
                'fade',
                'pop',
                'zoom',
                'slide_up',
                'slide_down',
                'slide_left',
                'slide_right',
              ] as const
            ).map((id) => ({ id, label: t(`cz.anims.${id}`) }))}
            onChange={(v) => up({ anim_in: v })}
          />
        </Row>
        <Row label={t('cz.animLoop')}>
          <Select
            label={t('cz.animLoop')}
            value={layer.loop}
            options={(['none', 'pulse', 'shake', 'float'] as const).map((id) => ({
              id,
              label: t(`cz.loops.${id}`),
            }))}
            onChange={(v) => up({ loop: v })}
          />
        </Row>
        <Row label={t('cz.animOut')}>
          <Segmented
            label={t('cz.animOut')}
            value={layer.anim_out}
            options={(['fade', 'none'] as const).map((id) => ({ id, label: t(`cz.outs.${id}`) }))}
            onChange={(v) => up({ anim_out: v })}
          />
        </Row>
      </Section>
    </>
  )
}
