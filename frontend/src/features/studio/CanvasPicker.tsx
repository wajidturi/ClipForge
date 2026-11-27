/** Video size: 5 presets (portrait + landscape) or any custom width x height. */
import { ArrowLeftRight } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import {
  DEFAULT_LIMITS,
  canvasProblem,
  type CanvasLimits,
  type CanvasPreset,
  type CanvasValue,
} from './canvas'

/** A small rectangle with the shape of the size. */
function Shape({ w, h, active }: { w: number; h: number; active: boolean }) {
  const k = 22 / Math.max(w, h)
  return (
    <span className="flex size-7 items-center justify-center" aria-hidden>
      <span
        className={cn('block rounded-[3px] border-2', active ? 'border-accent' : 'border-muted')}
        style={{ width: Math.max(6, w * k), height: Math.max(6, h * k) }}
      />
    </span>
  )
}

export function CanvasPicker({
  value,
  onChange,
  presets,
  limits = DEFAULT_LIMITS,
  compact = false,
}: {
  value: CanvasValue
  onChange: (c: CanvasValue) => void
  presets: CanvasPreset[]
  limits?: CanvasLimits
  compact?: boolean
}) {
  const { t } = useTranslation()
  const custom = value.preset === 'custom'
  // Typed text, so half-typed numbers ("7" on the way to "720") are not rejected. It is
  // dropped as soon as the size changes some other way (a preset, undo).
  const key = `${value.w}x${value.h}`
  const [draft, setDraft] = useState<{ key: string; w: string; h: string } | null>(null)
  const w = draft?.key === key ? draft.w : String(value.w)
  const h = draft?.key === key ? draft.h : String(value.h)
  const problem = custom ? canvasProblem(Number(w), Number(h), limits) : null

  const typed = (nw: string, nh: string) => {
    const a = Math.round(Number(nw))
    const b = Math.round(Number(nh))
    const ok = !canvasProblem(a, b, limits)
    const next = { preset: 'custom' as const, w: a - (a % 2), h: b - (b % 2) }
    setDraft({ key: ok ? `${next.w}x${next.h}` : key, w: nw, h: nh })
    if (ok) onChange(next)
  }

  const options = [...presets, { id: 'custom', label: t('canvas.anySize'), w: value.w, h: value.h }]
  return (
    <div className="space-y-2">
      <div
        className={cn('grid gap-1.5', compact ? 'grid-cols-3 sm:grid-cols-6' : 'grid-cols-3')}
        role="radiogroup"
        aria-label={t('canvas.label')}
      >
        {options.map((p) => {
          const on = value.preset === p.id
          return (
            <button
              key={p.id}
              type="button"
              role="radio"
              aria-checked={on}
              title={`${p.label} · ${p.w}×${p.h}`}
              onClick={() =>
                onChange(
                  p.id === 'custom'
                    ? { preset: 'custom', w: value.w, h: value.h }
                    : { preset: p.id as CanvasValue['preset'], w: p.w, h: p.h },
                )
              }
              className={cn(
                'flex flex-col items-center gap-0.5 rounded-md border px-1 py-1.5 text-[11px] leading-tight transition',
                on ? 'border-accent bg-accent/10' : 'border-border hover:bg-surface-2',
              )}
            >
              <Shape w={p.w} h={p.h} active={on} />
              <span className="font-medium">{p.id === 'custom' ? t('canvas.custom') : p.id}</span>
              <span className="w-full truncate text-center text-[10px] text-muted">{p.label}</span>
            </button>
          )
        })}
      </div>
      {custom && (
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label className="flex items-center gap-1.5">
              <span className="text-xs text-muted">{t('canvas.width')}</span>
              <input
                type="number"
                inputMode="numeric"
                min={limits.min}
                max={limits.max}
                step={2}
                value={w}
                onChange={(e) => typed(e.target.value, h)}
                aria-label={t('canvas.width')}
                aria-invalid={!!problem}
                className="h-8 w-20 rounded-md border border-border bg-surface-2 px-2 tabular-nums"
              />
            </label>
            <span className="text-muted">×</span>
            <label className="flex items-center gap-1.5">
              <span className="text-xs text-muted">{t('canvas.height')}</span>
              <input
                type="number"
                inputMode="numeric"
                min={limits.min}
                max={limits.max}
                step={2}
                value={h}
                onChange={(e) => typed(w, e.target.value)}
                aria-label={t('canvas.height')}
                aria-invalid={!!problem}
                className="h-8 w-20 rounded-md border border-border bg-surface-2 px-2 tabular-nums"
              />
            </label>
            <button
              type="button"
              onClick={() => typed(h, w)}
              className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-fg"
              title={t('canvas.swap')}
              aria-label={t('canvas.swap')}
            >
              <ArrowLeftRight size={14} />
            </button>
          </div>
          <p className={cn('text-[11px]', problem ? 'text-danger' : 'text-muted')} role="status">
            {problem ? t(`canvas.problem.${problem}`, limits) : t('canvas.customHelp', limits)}
          </p>
        </div>
      )}
    </div>
  )
}
