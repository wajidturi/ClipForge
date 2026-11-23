import { Film } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Badge } from '@/components/ui'
import { mediaUrl, type ShortPick, type ShortStatus } from '@/lib/api/client'
import { previewUrl } from '@/lib/runs'
import { cn } from '@/lib/utils'
import { QC_TONE, STATUS_TONE } from './status'

export function StatusBadge({ status }: { status: ShortStatus }) {
  const { t } = useTranslation()
  return <Badge tone={STATUS_TONE[status]}>{t(`shorts.status.${status}`)}</Badge>
}

export function QcBadge({ verdict }: { verdict: string | null | undefined }) {
  const { t } = useTranslation()
  if (!verdict) return null
  return <Badge tone={QC_TONE[verdict] ?? 'neutral'}>QC {t(`render.qc.${verdict}`)}</Badge>
}

/** 9:16 thumbnail: rendered cover, else the analysis preview strip, else an icon. */
export function ShortThumb({ short, className }: { short: ShortPick; className?: string }) {
  const [broken, setBroken] = useState(false)
  const part = short.parts?.[0]
  const cover = short.active?.cover_asset_id
  const src = cover
    ? mediaUrl(cover)
    : short.has_preview && part
      ? previewUrl(short.id, part.start_s, part.end_s)
      : null
  return (
    <div className={cn('relative aspect-[9/16] overflow-hidden bg-surface-2', className)}>
      {src && !broken ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          onError={() => setBroken(true)}
          className={cn('size-full', cover ? 'object-cover' : 'object-contain')}
        />
      ) : (
        <div className="flex size-full items-center justify-center text-muted">
          <Film size={22} aria-hidden />
        </div>
      )}
    </div>
  )
}

export function ShortTile({
  short,
  selected,
  onToggle,
}: {
  short: ShortPick
  selected?: boolean
  onToggle?: () => void
}) {
  const { t } = useTranslation()
  const part = short.parts?.[0]
  const secs = short.active?.duration_s ?? (part ? part.end_s - part.start_s : null)
  return (
    <div
      className={cn(
        'group relative overflow-hidden rounded-xl border bg-surface transition',
        selected ? 'border-accent ring-2 ring-accent/30' : 'border-border hover:border-muted',
      )}
      data-testid="short-tile"
    >
      <Link
        to={`/shorts/${short.id}`}
        className="block"
        aria-label={short.hook ?? short.title ?? ''}
      >
        <ShortThumb short={short} />
        <div className="space-y-1.5 p-3">
          <p className="line-clamp-2 text-sm font-semibold leading-snug tracking-wide">
            {short.hook || short.title || t('shorts.untitled')}
          </p>
          <p className="truncate text-xs text-muted">
            {[short.source_title, secs != null ? `${Math.round(secs)}s` : null]
              .filter(Boolean)
              .join(' · ')}
          </p>
          <div className="flex flex-wrap gap-1">
            <StatusBadge status={short.status} />
            <QcBadge verdict={short.active?.qc_verdict} />
          </div>
        </div>
      </Link>
      {onToggle && (
        <label className="absolute top-2 left-2 flex size-7 cursor-pointer items-center justify-center rounded-md bg-black/55 backdrop-blur-sm">
          <input
            type="checkbox"
            checked={!!selected}
            onChange={onToggle}
            aria-label={t('shorts.select')}
            className="size-4 accent-accent"
          />
        </label>
      )}
    </div>
  )
}
