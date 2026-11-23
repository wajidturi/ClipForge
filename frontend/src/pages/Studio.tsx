import { ArrowLeft, Check, Download, Palette, RotateCcw, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams, useSearchParams } from 'react-router'
import { Button, Card, Progress } from '@/components/ui'
import { QcBadge, StatusBadge } from '@/features/shorts/ShortTile'
import { Customizer } from '@/features/studio/Customizer'
import { AIEditTab, CaptionsTab, PostTab, TrimTab } from '@/features/studio/tabs'
import { mediaUrl, type ShortVersion } from '@/lib/api/client'
import { useJob } from '@/lib/jobs'
import { exportUrl, useReview, useShort } from '@/lib/shorts'
import { cn, formatClock } from '@/lib/utils'

const TABS = ['customize', 'post', 'trim', 'captions', 'ai'] as const
type Tab = (typeof TABS)[number]

function VersionList({
  versions,
  current,
  activeId,
  onPick,
}: {
  versions: ShortVersion[]
  current: string | undefined
  activeId: string | undefined
  onPick: (id: string) => void
}) {
  const { t } = useTranslation()
  if (versions.length < 2) return null
  return (
    <div>
      <h3 className="mb-1.5 text-xs font-medium text-muted">{t('studio.versions')}</h3>
      <ul className="space-y-1">
        {versions.map((v) => (
          <li key={v.id}>
            <button
              onClick={() => onPick(v.id)}
              className={cn(
                'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs',
                v.id === current ? 'bg-accent/12 text-accent' : 'hover:bg-surface-2',
              )}
            >
              <span className="font-medium">v{v.version_no}</span>
              <span className="flex-1 truncate text-muted">
                {t(`studio.origin.${v.origin}`, { defaultValue: v.origin })} · {v.style} ·{' '}
                {v.layout}
              </span>
              {v.id === activeId && <span className="text-[10px] text-ok">●</span>}
              <QcBadge verdict={v.qc_verdict} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function Studio() {
  const { t } = useTranslation()
  const { id = '' } = useParams()
  const short = useShort(id)
  const s = short.data
  const [params, setParams] = useSearchParams()
  const tab: Tab = (TABS as readonly string[]).includes(params.get('tab') ?? '')
    ? (params.get('tab') as Tab)
    : 'customize'
  const [viewing, setViewing] = useState<string | null>(null)
  const job = useJob(s?.status === 'rendering' ? s.render_job_id : null)
  const review = useReview()

  if (short.isError) return <p className="px-8 py-8 text-sm text-danger">{t('studio.notFound')}</p>
  if (!s) return <p className="px-8 py-8 text-sm text-muted">…</p>

  const shown =
    (s.versions ?? []).find((v) => v.id === viewing) ??
    (s.versions ?? []).find((v) => v.id === s.active?.id) ??
    s.versions?.[0]
  const part = s.parts?.[0]

  return (
    <div className={cn('mx-auto px-8 py-8', tab === 'customize' ? 'max-w-[96rem]' : 'max-w-6xl')}>
      <Link
        to={s.run_id ? `/runs/${s.run_id}` : '/shorts'}
        className="mb-4 inline-flex items-center gap-1 text-xs text-muted hover:text-fg"
      >
        <ArrowLeft size={13} aria-hidden /> {s.run_id ? t('studio.backRun') : t('nav.library')}
      </Link>
      <header className="mb-6 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold tracking-tight">{s.hook || t('shorts.untitled')}</h1>
          <p className="mt-1 text-sm text-muted">
            {[
              s.source_title,
              part ? `${formatClock(part.start_s)}–${formatClock(part.end_s)}` : null,
              s.credit,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        <StatusBadge status={s.status} />
        {(s.status === 'review' || s.status === 'rejected' || s.status === 'failed') &&
          s.active && (
            <Button
              size="sm"
              onClick={() => review.mutate({ id: s.id, action: 'approve' })}
              disabled={review.isPending}
            >
              <Check size={14} aria-hidden /> {t('review.approve')}
            </Button>
          )}
        {(s.status === 'review' ||
          s.status === 'approved' ||
          s.status === 'picked' ||
          s.status === 'failed') && (
          <Button
            size="sm"
            variant="danger"
            onClick={() => review.mutate({ id: s.id, action: 'reject' })}
            disabled={review.isPending}
          >
            <X size={14} aria-hidden /> {t('review.reject')}
          </Button>
        )}
        {(s.status === 'approved' || s.status === 'rejected') && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => review.mutate({ id: s.id, action: 'reopen' })}
          >
            <RotateCcw size={14} aria-hidden /> {t('review.reopen')}
          </Button>
        )}
        {s.active?.mp4_asset_id && (
          <a
            href={exportUrl(s.id)}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-3 text-xs font-medium hover:bg-border/60"
          >
            <Download size={14} aria-hidden /> {t('studio.export')}
          </a>
        )}
      </header>
      {review.error && <p className="mb-4 text-sm text-danger">{review.error.message}</p>}

      <div className="mb-5 flex gap-1 overflow-x-auto border-b border-border" role="tablist">
        {TABS.map((k) => (
          <button
            key={k}
            role="tab"
            aria-selected={k === tab}
            onClick={() => setParams({ tab: k }, { replace: true })}
            className={cn(
              '-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm whitespace-nowrap transition',
              k === tab
                ? 'border-accent font-medium text-fg'
                : 'border-transparent text-muted hover:text-fg',
            )}
          >
            {k === 'customize' && <Palette size={14} aria-hidden />}
            {t(`studio.tabs.${k}`)}
          </button>
        ))}
      </div>

      {tab === 'customize' ? (
        <Customizer short={s} />
      ) : (
        <div className="grid gap-6 md:grid-cols-[minmax(0,20rem)_1fr]">
          <div className="space-y-4">
            {s.status === 'rendering' && (
              <Card className="space-y-1.5 p-3">
                <Progress value={job.data?.progress ?? 0} />
                <p className="text-xs text-muted">{job.data?.step ?? t('render.queued')}</p>
              </Card>
            )}
            {shown?.mp4_asset_id ? (
              <video
                key={shown.id}
                controls
                playsInline
                poster={shown.cover_asset_id ? mediaUrl(shown.cover_asset_id) : undefined}
                src={mediaUrl(shown.mp4_asset_id)}
                className="aspect-[9/16] w-full rounded-xl bg-black object-contain"
                aria-label={t('render.player')}
              />
            ) : (
              <div className="flex aspect-[9/16] items-center justify-center rounded-xl bg-surface-2 px-6 text-center text-sm text-muted">
                {t('studio.notRendered')}
              </div>
            )}
            {shown && (
              <div className="space-y-1 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <QcBadge verdict={shown.qc_verdict} />
                  <span className="text-muted">
                    v{shown.version_no}
                    {shown.duration_s ? ` · ${Math.round(shown.duration_s)}s` : ''}
                  </span>
                  {shown.mp4_asset_id && (
                    <a
                      href={mediaUrl(shown.mp4_asset_id)}
                      download
                      className="ml-auto text-accent hover:underline"
                    >
                      MP4
                    </a>
                  )}
                </div>
                {(shown.qc_reasons?.length ?? 0) > 0 && (
                  <ul className="text-warn">
                    {shown.qc_reasons!.map((r, i) => (
                      <li key={i}>• {r}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <VersionList
              versions={s.versions ?? []}
              current={shown?.id}
              activeId={s.active?.id}
              onPick={setViewing}
            />
          </div>

          <Card className="min-w-0">
            <div className="p-5" role="tabpanel">
              {/* key: start from the saved values again after any server-side change */}
              {tab === 'post' && <PostTab key={s.updated_at} short={s} />}
              {tab === 'trim' && <TrimTab key={s.updated_at} short={s} />}
              {tab === 'captions' && <CaptionsTab short={s} />}
              {tab === 'ai' && <AIEditTab short={s} />}
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
