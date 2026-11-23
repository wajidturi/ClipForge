/** Visual template cards (a tiny wireframe of each layout) used across the app. */
import { useTranslation } from 'react-i18next'
import type { TemplateChoice, TemplateInfo } from '@/lib/api/client'
import { cn } from '@/lib/utils'

export function TemplateIcon({ id, className }: { id: string; className?: string }) {
  const cam = 'fill-fuchsia-400/90'
  const game = 'fill-sky-500/80'
  const accent = 'fill-yellow-300'
  return (
    <svg viewBox="0 0 36 64" className={cn('h-14 w-8 shrink-0', className)} aria-hidden>
      <rect width="36" height="64" rx="4" className="fill-slate-900" />
      {id === 'streamer_first' && (
        <>
          <rect x="2" y="2" width="32" height="25" rx="2.5" className={cam} />
          <rect x="2" y="29" width="32" height="33" rx="2.5" className={game} />
          <rect x="6" y="50" width="24" height="5" rx="1.5" className={accent} />
        </>
      )}
      {id === 'gameplay_first' && (
        <>
          <rect x="2" y="2" width="32" height="38" rx="2.5" className={game} />
          <rect x="2" y="42" width="32" height="20" rx="2.5" className={cam} />
          <rect x="8" y="6" width="20" height="5" rx="1.5" className="fill-red-500" />
        </>
      )}
      {id === 'dual_vision' && (
        <>
          <rect x="2" y="2" width="32" height="29" rx="2.5" className={cam} />
          <rect x="2" y="33" width="32" height="29" rx="2.5" className={game} />
          <polygon points="0,34 36,28 36,35 0,41" className="fill-violet-500" />
        </>
      )}
      {id === 'floating_facecam' && (
        <>
          <rect x="1" y="1" width="34" height="62" rx="3.5" className={game} />
          <circle cx="11" cy="49" r="7.5" className={cam} stroke="#c4b5fd" strokeWidth="1.2" />
          <rect x="6" y="7" width="24" height="5" rx="1.5" className="fill-white" />
        </>
      )}
      {id === 'cinematic' && (
        <>
          <rect x="1" y="1" width="34" height="62" rx="3.5" className={game} />
          {[0, 1, 2, 3, 4, 5].map((k) => (
            <line
              key={k}
              x1="18"
              y1="32"
              x2={18 + 16 * Math.cos(k + 0.3)}
              y2={32 + 28 * Math.sin(k + 0.3)}
              stroke="white"
              strokeOpacity="0.5"
              strokeWidth="0.7"
            />
          ))}
          <polygon
            points="18,8 21,12 26,11 23,15 26,19 21,18 18,22 15,18 10,19 13,15 10,11 15,12"
            className="fill-red-600"
          />
          <rect x="5" y="48" width="26" height="6" rx="1.5" className={accent} />
        </>
      )}
      {id === 'auto' && (
        <text x="18" y="38" textAnchor="middle" fontSize="16" className="fill-white">
          ✦
        </text>
      )}
    </svg>
  )
}

export function TemplatePicker({
  value,
  onChange,
  templates,
  withAuto = false,
  compact = false,
}: {
  value: TemplateChoice
  onChange: (t: TemplateChoice) => void
  templates: TemplateInfo[]
  withAuto?: boolean
  compact?: boolean
}) {
  const { t } = useTranslation()
  const items: { id: TemplateChoice; name: string; tagline: string }[] = [
    ...(withAuto
      ? [{ id: 'auto' as const, name: t('tpl.auto.name'), tagline: t('tpl.auto.tagline') }]
      : []),
    ...templates.map((x) => ({ id: x.id as TemplateChoice, name: x.name, tagline: x.tagline })),
  ]
  return (
    <div
      role="radiogroup"
      aria-label={t('tpl.label')}
      className={cn(
        'grid gap-2',
        compact ? 'grid-cols-2 sm:grid-cols-3 xl:grid-cols-5' : 'grid-cols-2 md:grid-cols-3',
      )}
    >
      {items.map((x) => (
        <button
          key={x.id}
          type="button"
          role="radio"
          aria-checked={value === x.id}
          title={x.tagline}
          onClick={() => onChange(x.id)}
          className={cn(
            'group flex items-center gap-2.5 rounded-xl border p-2 text-left transition',
            value === x.id
              ? 'border-accent bg-accent/10 shadow-[0_0_0_3px] shadow-accent/20'
              : 'border-border hover:-translate-y-0.5 hover:border-muted hover:bg-surface-2',
          )}
        >
          <TemplateIcon id={x.id} className="transition group-hover:scale-105" />
          <span className="min-w-0">
            <span className="block text-xs font-semibold">{x.name}</span>
            {!compact && (
              <span className="mt-0.5 block text-[11px] leading-tight text-muted">{x.tagline}</span>
            )}
          </span>
        </button>
      ))}
    </div>
  )
}
