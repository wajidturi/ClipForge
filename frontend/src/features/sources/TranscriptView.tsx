import { Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TranscriptSegment } from '@/lib/api/client'
import { cn, formatClock } from '@/lib/utils'
import { HOT, SIGNAL_STYLE, TAG_TO_SIGNAL, activeIndex, heatColor } from './markers'

export function TranscriptView({
  segments,
  now,
  onSeek,
}: {
  segments: TranscriptSegment[]
  now: number | null
  onSeek: (t: number) => void
}) {
  const { t } = useTranslation()
  const [q, setQ] = useState('')
  const [hotOnly, setHotOnly] = useState(false)
  const [follow, setFollow] = useState(true)
  const active = activeIndex(segments, now)
  const activeRef = useRef<HTMLLIElement | null>(null)

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return segments.filter(
      (s) => (!hotOnly || s.heat >= HOT) && (!needle || s.text.toLowerCase().includes(needle)),
    )
  }, [segments, q, hotOnly])

  useEffect(() => {
    if (follow && activeRef.current) activeRef.current.scrollIntoView?.({ block: 'nearest' })
  }, [active, follow])

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3 text-xs">
        <label className="relative">
          <Search
            size={13}
            className="absolute top-1/2 left-2 -translate-y-1/2 text-muted"
            aria-hidden
          />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('transcript.search')}
            aria-label={t('transcript.search')}
            className="h-7 w-52 rounded-md border border-border bg-surface-2 pr-2 pl-7"
          />
        </label>
        <label className="flex items-center gap-1.5 text-muted">
          <input
            type="checkbox"
            checked={hotOnly}
            onChange={(e) => setHotOnly(e.target.checked)}
            className="size-3.5 accent-accent"
          />
          {t('transcript.hotOnly', { n: HOT })}
        </label>
        <label className="flex items-center gap-1.5 text-muted">
          <input
            type="checkbox"
            checked={follow}
            onChange={(e) => setFollow(e.target.checked)}
            className="size-3.5 accent-accent"
          />
          {t('transcript.follow')}
        </label>
        <span className="ml-auto text-muted">
          {t('transcript.count', { shown: shown.length, total: segments.length })}
        </span>
      </div>
      <ol className="max-h-[32rem] overflow-y-auto" aria-label={t('transcript.title')}>
        {shown.map((s) => {
          const isActive = segments[active]?.idx === s.idx
          return (
            <li
              key={s.idx}
              ref={isActive ? activeRef : undefined}
              data-testid="segment"
              className={cn(
                'flex cursor-pointer gap-3 border-l-2 px-5 py-2 text-sm transition hover:bg-surface-2',
                isActive ? 'border-accent bg-accent/8' : 'border-transparent',
              )}
              onClick={() => onSeek(s.start_s)}
            >
              <span className="w-14 shrink-0 pt-0.5 font-mono text-xs text-muted tabular-nums">
                {formatClock(s.start_s)}
              </span>
              <span
                className="mt-1 h-3 w-1.5 shrink-0 rounded-full"
                style={{ background: heatColor(s.heat) }}
                title={t('transcript.heat', { n: Math.round(s.heat) })}
              />
              <span className="min-w-0 flex-1">
                {s.text}
                {s.tags.length > 0 && (
                  <span className="mt-1 flex flex-wrap gap-1">
                    {s.tags.map((tag, i) => {
                      const style = SIGNAL_STYLE[TAG_TO_SIGNAL[String(tag.type)] ?? '']
                      return (
                        <span
                          key={i}
                          className="rounded px-1.5 py-px text-[10px] font-semibold tracking-wide"
                          style={{
                            color: style?.color,
                            background: `${style?.color ?? '#888'}22`,
                          }}
                        >
                          {String(tag.type)}
                          {tag.label ? ` · ${String(tag.label)}` : ''}
                        </span>
                      )
                    })}
                  </span>
                )}
              </span>
              {s.heat > 0 && (
                <span className="w-8 shrink-0 text-right text-xs text-muted tabular-nums">
                  {Math.round(s.heat)}
                </span>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
