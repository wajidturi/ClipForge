import { ChevronDown, ExternalLink, FileVideo, Loader2, RotateCcw, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Badge, Button, Progress, type Tone } from '@/components/ui'
import { mediaUrl, type Source, type SourceStatus } from '@/lib/api/client'
import { useJob } from '@/lib/jobs'
import { IN_PROGRESS, useDeleteSource, useRetrySource, useSource } from '@/lib/sources'
import { cn, formatBytes, formatClock } from '@/lib/utils'

const TONE: Record<SourceStatus, Tone> = {
  new: 'neutral',
  downloading: 'info',
  analyzing: 'info',
  ready: 'ok',
  failed: 'danger',
  skipped: 'warn',
}

function Thumb({ src }: { src: Source }) {
  const [broken, setBroken] = useState(false)
  if (src.thumbnail && !broken)
    return (
      <img
        src={src.thumbnail}
        alt=""
        referrerPolicy="no-referrer"
        loading="lazy"
        onError={() => setBroken(true)}
        className="aspect-video w-32 shrink-0 rounded-md bg-surface-2 object-cover"
      />
    )
  return (
    <div className="flex aspect-video w-32 shrink-0 items-center justify-center rounded-md bg-surface-2 text-muted">
      <FileVideo size={20} aria-hidden />
    </div>
  )
}

function Details({ id }: { id: string }) {
  const { t } = useTranslation()
  const { data } = useSource(id)
  if (!data) return <div className="px-5 pb-4 text-xs text-muted">…</div>
  const assets = data.assets ?? []
  const audio = assets.find((a) => a.kind === 'audio')
  const video = assets.find((a) => a.kind === 'video')
  return (
    <div className="space-y-3 border-t border-border bg-surface-2/40 px-5 py-4 text-sm">
      {video ? (
        <video
          controls
          preload="metadata"
          src={mediaUrl(video.id)}
          className="max-h-72 w-full rounded-md bg-black"
        />
      ) : (
        audio && <audio controls preload="none" src={mediaUrl(audio.id)} className="w-full" />
      )}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-4">
        <div>
          <dt className="text-muted">{t('sources.detail.length')}</dt>
          <dd>{formatClock(data.duration_s)}</dd>
        </div>
        <div>
          <dt className="text-muted">{t('sources.detail.window')}</dt>
          <dd>
            {data.window_start_s != null || data.window_end_s != null
              ? `${formatClock(data.window_start_s ?? 0)} – ${formatClock(data.window_end_s ?? data.duration_s)}`
              : t('sources.detail.whole')}
          </dd>
        </div>
        <div>
          <dt className="text-muted">{t('sources.detail.audio')}</dt>
          <dd>{audio ? formatBytes(audio.bytes) : '–'}</dd>
        </div>
        <div>
          <dt className="text-muted">{t('sources.detail.chapters')}</dt>
          <dd>{data.chapters?.length || '–'}</dd>
        </div>
      </dl>
      {data.window_note && <p className="text-xs text-warn">{data.window_note}</p>}
      {data.platform !== 'file' && (
        <a
          href={data.url}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
        >
          <ExternalLink size={12} aria-hidden /> {t('sources.detail.open')}
        </a>
      )}
    </div>
  )
}

export function SourceRow({ src, platformName }: { src: Source; platformName: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const busy = IN_PROGRESS.includes(src.status)
  const job = useJob(busy ? src.latest_job_id : null)
  const retry = useRetrySource()
  const del = useDeleteSource()

  return (
    <li data-testid="source-row">
      <div className="flex gap-4 px-5 py-4">
        <Thumb src={src} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <h3
              className="min-w-0 flex-1 truncate text-sm font-medium"
              title={src.title ?? src.url}
            >
              <Link to={`/sources/${src.id}`} className="hover:text-accent hover:underline">
                {src.title ?? src.url}
              </Link>
            </h3>
            <Badge tone={TONE[src.status]}>{t(`sources.status.${src.status}`)}</Badge>
          </div>
          <p className="mt-0.5 truncate text-xs text-muted">
            {[src.channel_name, platformName, src.duration_s ? formatClock(src.duration_s) : null]
              .filter(Boolean)
              .join(' · ')}
          </p>

          {busy && (
            <div className="mt-2.5 space-y-1">
              <Progress value={job.data?.progress ?? 0} />
              <p className="text-xs text-muted">{job.data?.step ?? t('sources.status.new')}</p>
            </div>
          )}
          {src.status === 'failed' && src.error && (
            <div className="mt-2 rounded-md bg-danger/10 p-2 text-xs">
              <p className="text-danger">{src.error}</p>
              {src.error_hint && <p className="mt-0.5 text-muted">{src.error_hint}</p>}
            </div>
          )}
          {src.status === 'skipped' && src.skip_reason && (
            <p className="mt-2 text-xs text-warn">{src.skip_reason}</p>
          )}

          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            {(src.status === 'ready' || src.status === 'failed') && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setOpen((o) => !o)}
                aria-expanded={open}
              >
                <ChevronDown
                  size={14}
                  className={cn('transition', open && 'rotate-180')}
                  aria-hidden
                />
                {t('sources.actions.details')}
              </Button>
            )}
            {src.status === 'failed' && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => retry.mutate(src.id)}
                disabled={retry.isPending}
              >
                <RotateCcw size={14} aria-hidden /> {t('sources.actions.retry')}
              </Button>
            )}
            {!confirming ? (
              <Button size="sm" variant="ghost" onClick={() => setConfirming(true)}>
                <Trash2 size={14} aria-hidden /> {t('sources.actions.delete')}
              </Button>
            ) : (
              <span className="flex items-center gap-1.5 text-xs">
                {t('sources.actions.confirm')}
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => del.mutate(src.id)}
                  disabled={del.isPending}
                >
                  {del.isPending && <Loader2 size={12} className="animate-spin" aria-hidden />}
                  {t('sources.actions.yesDelete')}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                  {t('sources.actions.keep')}
                </Button>
              </span>
            )}
          </div>
        </div>
      </div>
      {open && <Details id={src.id} />}
    </li>
  )
}
