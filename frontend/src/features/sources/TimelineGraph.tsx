import { useMemo, useState, type MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'
import type { Timeline } from '@/lib/api/client'
import { formatClock } from '@/lib/utils'
import { SIGNAL_STYLE, heatColor } from './markers'

const W = 1000
const H = 140
const HEAT_TOP = 18
const HEAT_H = 78
const MARK_Y = 104

function path(values: number[], h: number, top: number): string {
  if (!values.length) return ''
  const dx = W / values.length
  return values
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(i + 0.5) * dx},${top + h - Math.min(1, v) * h}`)
    .join(' ')
}

type Layer = 'loud' | 'chat' | 'motion' | 'replay'

/**
 * Heat bars (0-100) per time bin, with loudness / chat / motion / replay curves on top
 * and a row of signal markers. Click anywhere to seek. Times are full-video seconds.
 */
export function TimelineGraph({
  data,
  now,
  onSeek,
}: {
  data: Timeline
  now: number | null
  onSeek: (t: number) => void
}) {
  const { t } = useTranslation()
  const [hover, setHover] = useState<number | null>(null)
  const [layers, setLayers] = useState<Record<Layer, boolean>>({
    loud: true,
    chat: true,
    motion: false,
    replay: true,
  })
  const span = Math.max(1e-6, data.end_s - data.start_s)
  const x = (time: number) => ((time - data.start_s) / span) * W
  const timeAt = (e: MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    return data.start_s + ((e.clientX - r.left) / r.width) * span
  }
  const dx = W / Math.max(1, data.heat.length)
  const has = {
    loud: data.loud.some((v) => v > 0),
    chat: data.chat.some((v) => v > 0),
    motion: data.motion.some((v) => v > 0),
    replay: data.replay.some((v) => v > 0),
  }
  const curves: { key: Layer; color: string; values: number[] }[] = useMemo(
    () => [
      { key: 'loud', color: SIGNAL_STYLE.loud.color, values: data.loud },
      { key: 'chat', color: SIGNAL_STYLE.chat_spike.color, values: data.chat },
      { key: 'motion', color: SIGNAL_STYLE.moment.color, values: data.motion },
      { key: 'replay', color: SIGNAL_STYLE.replay.color, values: data.replay },
    ],
    [data],
  )

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-3 text-xs text-muted">
        {curves
          .filter((c) => has[c.key])
          .map((c) => (
            <label key={c.key} className="flex cursor-pointer items-center gap-1.5">
              <input
                type="checkbox"
                checked={layers[c.key]}
                onChange={(e) => setLayers((l) => ({ ...l, [c.key]: e.target.checked }))}
                className="size-3.5 accent-accent"
              />
              <span className="inline-block h-0.5 w-4" style={{ background: c.color }} />
              {t(`timeline.layer.${c.key}`)}
            </label>
          ))}
        <span className="ml-auto">
          {hover != null
            ? formatClock(hover)
            : `${formatClock(data.start_s)} – ${formatClock(data.end_s)}`}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="h-36 w-full cursor-crosshair rounded-md bg-surface-2"
        role="img"
        aria-label={t('timeline.aria')}
        onClick={(e) => onSeek(timeAt(e))}
        onMouseMove={(e) => setHover(timeAt(e))}
        onMouseLeave={() => setHover(null)}
      >
        {data.heat.map((h, i) =>
          h > 0 ? (
            <rect
              key={i}
              x={i * dx}
              width={Math.max(1, dx - 0.5)}
              y={HEAT_TOP + HEAT_H - (h / 100) * HEAT_H}
              height={(h / 100) * HEAT_H}
              fill={heatColor(h)}
              opacity={0.85}
            />
          ) : null,
        )}
        {curves
          .filter((c) => has[c.key] && layers[c.key])
          .map((c) => (
            <path
              key={c.key}
              d={path(c.values, HEAT_H, HEAT_TOP)}
              fill="none"
              stroke={c.color}
              strokeWidth={1.5}
              vectorEffect="non-scaling-stroke"
              opacity={0.9}
            />
          ))}
        {data.markers.map((m, i) => (
          <rect
            key={i}
            data-testid="marker"
            x={x(m.start_s)}
            width={Math.max(3, x(m.end_s) - x(m.start_s))}
            y={MARK_Y + (Object.keys(SIGNAL_STYLE).indexOf(m.type) % 4) * 8}
            height={6}
            rx={2}
            fill={SIGNAL_STYLE[m.type]?.color ?? '#999'}
          >
            <title>{`${formatClock(m.start_s)} · ${m.label ?? m.type}`}</title>
          </rect>
        ))}
        {now != null && now >= data.start_s && now <= data.end_s && (
          <line
            x1={x(now)}
            x2={x(now)}
            y1={0}
            y2={H}
            stroke="currentColor"
            className="text-fg"
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>
    </div>
  )
}
