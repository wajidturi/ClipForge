import { AlertTriangle, ArrowLeft, ExternalLink, Loader2, RefreshCw } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import { Badge, Button, Card, CardHeader, Progress } from '@/components/ui'
import { TimelineGraph } from '@/features/sources/TimelineGraph'
import { TranscriptView } from '@/features/sources/TranscriptView'
import { mediaUrl } from '@/lib/api/client'
import { useJob } from '@/lib/jobs'
import { IN_PROGRESS, useAnalyze, useSource, useTimeline, useTranscript } from '@/lib/sources'
import { formatClock } from '@/lib/utils'

function AnalyzePanel({ id, disabled }: { id: string; disabled: boolean }) {
  const { t } = useTranslation()
  const analyze = useAnalyze(id)
  const [vision, setVision] = useState(true)
  const [banners, setBanners] = useState(false)
  const [force, setForce] = useState(false)
  const box = (label: string, v: boolean, set: (b: boolean) => void) => (
    <label className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        checked={v}
        onChange={(e) => set(e.target.checked)}
        className="size-4 accent-accent"
      />
      {label}
    </label>
  )
  return (
    <div className="space-y-2.5 p-5">
      {box(t('analysis.opt.vision'), vision, setVision)}
      {box(t('analysis.opt.banners'), banners, setBanners)}
      {box(t('analysis.opt.force'), force, setForce)}
      <Button
        size="sm"
        disabled={disabled || analyze.isPending}
        onClick={() => analyze.mutate({ vision, banners, force_transcribe: force })}
      >
        {analyze.isPending ? (
          <Loader2 size={14} className="animate-spin" aria-hidden />
        ) : (
          <RefreshCw size={14} aria-hidden />
        )}
        {t('analysis.run')}
      </Button>
      {analyze.error && <p className="text-xs text-danger">{analyze.error.message}</p>}
    </div>
  )
}

export function SourceDetail() {
  const { t } = useTranslation()
  const { id = '' } = useParams()
  const source = useSource(id)
  const src = source.data
  const busy = src ? IN_PROGRESS.includes(src.status) : false
  const analysed = src?.status === 'ready'
  const transcript = useTranscript(id, analysed)
  const timeline = useTimeline(id, 400, analysed)
  const job = useJob(busy ? src?.latest_job_id : null)

  const mediaRef = useRef<HTMLMediaElement | null>(null)
  const [now, setNow] = useState<number | null>(null)
  const assets = src?.assets ?? []
  const video = assets.find((a) => a.kind === 'video')
  const audio = assets.find((a) => a.kind === 'audio')
  // The original video covers the whole file; the audio copy starts at the window start.
  const offset = video ? 0 : (src?.window_start_s ?? 0)

  const seek = useCallback(
    (time: number) => {
      const m = mediaRef.current
      if (!m) return
      m.currentTime = Math.max(0, time - offset)
      void m.play().catch(() => undefined)
    },
    [offset],
  )
  const onTime = () => mediaRef.current && setNow(mediaRef.current.currentTime + offset)

  if (source.isError)
    return <p className="px-8 py-8 text-sm text-danger">{t('analysis.notFound')}</p>
  if (!src) return <p className="px-8 py-8 text-sm text-muted">…</p>

  const warnings = timeline.data?.warnings ?? []
  const steps = timeline.data?.steps ?? {}

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <Link
        to="/sources"
        className="mb-4 inline-flex items-center gap-1 text-xs text-muted hover:text-fg"
      >
        <ArrowLeft size={13} aria-hidden /> {t('analysis.back')}
      </Link>
      <header className="mb-6 flex items-start gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-xl font-semibold tracking-tight">{src.title ?? src.url}</h1>
          <p className="mt-1 text-sm text-muted">
            {[
              src.channel_name,
              formatClock(src.duration_s),
              src.language?.toUpperCase(),
              src.window_start_s != null
                ? `${t('sources.detail.window')}: ${formatClock(src.window_start_s)}–${formatClock(src.window_end_s)}`
                : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        <Badge tone={analysed ? 'ok' : src.status === 'failed' ? 'danger' : 'info'}>
          {t(`sources.status.${src.status}`)}
        </Badge>
        {src.platform !== 'file' && (
          <a
            href={src.url}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
          >
            <ExternalLink size={12} aria-hidden /> {t('sources.detail.open')}
          </a>
        )}
      </header>

      {busy && (
        <Card className="mb-6 p-5">
          <Progress value={job.data?.progress ?? 0} />
          <p className="mt-2 text-sm text-muted">{job.data?.step ?? t('sources.status.new')}</p>
          {src.error && <p className="mt-1 text-xs text-warn">{src.error}</p>}
        </Card>
      )}
      {src.status === 'failed' && src.error && (
        <Card className="mb-6 flex gap-2 border-danger/40 p-4 text-sm">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-danger" aria-hidden />
          <div>
            <p className="text-danger">{src.error}</p>
            {src.error_hint && <p className="text-xs text-muted">{src.error_hint}</p>}
          </div>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_18rem]">
        <div className="min-w-0 space-y-6">
          <Card className="p-4">
            {video ? (
              <video
                ref={(el) => {
                  mediaRef.current = el
                }}
                controls
                preload="metadata"
                src={mediaUrl(video.id)}
                onTimeUpdate={onTime}
                className="max-h-96 w-full rounded-md bg-black"
              />
            ) : audio ? (
              <audio
                ref={(el) => {
                  mediaRef.current = el
                }}
                controls
                preload="metadata"
                src={mediaUrl(audio.id)}
                onTimeUpdate={onTime}
                className="w-full"
              />
            ) : (
              <p className="text-sm text-muted">{t('analysis.noMedia')}</p>
            )}
            {timeline.data && (
              <div className="mt-4">
                <TimelineGraph data={timeline.data} now={now} onSeek={seek} />
              </div>
            )}
          </Card>

          <Card>
            <CardHeader
              title={t('transcript.title')}
              action={
                transcript.data && (
                  <span className="text-xs text-muted">
                    {transcript.data.model} · {transcript.data.device.toUpperCase()} ·{' '}
                    {transcript.data.word_count} {t('transcript.words')}
                  </span>
                )
              }
            />
            {transcript.data ? (
              <TranscriptView segments={transcript.data.segments} now={now} onSeek={seek} />
            ) : (
              <p className="px-5 py-8 text-center text-sm text-muted">
                {analysed && !transcript.isError ? '…' : t('transcript.pending')}
              </p>
            )}
          </Card>
        </div>

        <aside className="space-y-6">
          <Card>
            <CardHeader title={t('analysis.title')} />
            <dl className="space-y-1.5 px-5 py-4 text-xs">
              {Object.entries(steps).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3">
                  <dt className="text-muted">{t(`analysis.step.${k}`, { defaultValue: k })}</dt>
                  <dd className="text-right">{v}</dd>
                </div>
              ))}
              {!Object.keys(steps).length && <p className="text-muted">{t('analysis.none')}</p>}
            </dl>
            {warnings.length > 0 && (
              <ul className="space-y-1 border-t border-border px-5 py-3 text-xs text-warn">
                {warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <CardHeader title={t('analysis.rerun')} />
            <AnalyzePanel id={id} disabled={busy || !audio} />
          </Card>
        </aside>
      </div>
    </div>
  )
}
