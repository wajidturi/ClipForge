import {
  Check,
  Clapperboard,
  Palette,
  ExternalLink,
  Pencil,
  SlidersHorizontal,
  Trash2,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Badge, Button, Card, Progress, type Tone } from '@/components/ui'
import { mediaUrl, type RenderRequest, type ShortPick } from '@/lib/api/client'
import { useJob } from '@/lib/jobs'
import { previewUrl, useDropShort, useEditShort, useRenderShort } from '@/lib/runs'
import { formatClock } from '@/lib/utils'

const QC_TONE: Record<string, Tone> = { pass: 'ok', warn: 'warn', fail: 'danger' }

function RenderState({ pick }: { pick: ShortPick }) {
  const { t } = useTranslation()
  const job = useJob(pick.status === 'rendering' ? pick.render_job_id : null)
  if (pick.status === 'rendering')
    return (
      <div className="space-y-1">
        <Progress value={job.data?.progress ?? 0} />
        <p className="text-xs text-muted">{job.data?.step ?? t('render.queued')}</p>
      </div>
    )
  const v = pick.active
  if (!v) return null
  return (
    <div className="space-y-1 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={QC_TONE[v.qc_verdict ?? ''] ?? 'neutral'}>
          QC {t(`render.qc.${v.qc_verdict ?? 'none'}`)}
        </Badge>
        <span className="text-muted">
          v{v.version_no} · {v.layout} · {v.style}
          {v.duration_s ? ` · ${Math.round(v.duration_s)}s` : ''}
          {v.render_ms ? ` · ${t('render.took', { s: Math.round(v.render_ms / 1000) })}` : ''}
        </span>
      </div>
      {v.qc_reasons && v.qc_reasons.length > 0 && (
        <ul className="text-warn">
          {v.qc_reasons.map((r, i) => (
            <li key={i}>• {r}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function parseClock(v: string): number | null {
  const parts = v.trim().split(':').map(Number)
  if (!parts.length || parts.some((p) => Number.isNaN(p) || p < 0)) return null
  return parts.reduce((acc, p) => acc * 60 + p, 0)
}

export function PickCard({
  pick,
  runId,
  rank,
  renderBody,
}: {
  pick: ShortPick
  runId: string
  rank: number
  renderBody: RenderRequest
}) {
  const { t } = useTranslation()
  const part = pick.parts?.[0]
  const edit = useEditShort(runId)
  const drop = useDropShort(runId)
  const render = useRenderShort(runId)
  const v = pick.active
  const [editing, setEditing] = useState(false)
  const [hook, setHook] = useState(pick.hook ?? '')
  const [title, setTitle] = useState(pick.title ?? '')
  const [start, setStart] = useState(formatClock(part?.start_s))
  const [end, setEnd] = useState(formatClock(part?.end_s))
  const [badPreview, setBadPreview] = useState(false)
  if (!part) return null
  const editable = pick.status === 'picked'

  const save = () => {
    const s = parseClock(start)
    const e = parseClock(end)
    edit.mutate(
      {
        id: pick.id,
        patch: {
          hook,
          title,
          ...(s != null && s !== Math.round(part.start_s) ? { start_s: s } : {}),
          ...(e != null && e !== Math.round(part.end_s) ? { end_s: e } : {}),
        },
      },
      { onSuccess: () => setEditing(false) },
    )
  }

  return (
    <Card className="overflow-hidden" data-testid="pick">
      {v?.mp4_asset_id ? (
        <video
          key={v.id}
          controls
          preload="metadata"
          playsInline
          poster={v.cover_asset_id ? mediaUrl(v.cover_asset_id) : undefined}
          src={mediaUrl(v.mp4_asset_id)}
          className="mx-auto aspect-[9/16] max-h-[28rem] w-full bg-black object-contain"
          aria-label={t('render.player')}
        />
      ) : pick.has_preview && !badPreview ? (
        <img
          src={previewUrl(pick.id, part.start_s, part.end_s)}
          alt={t('runs.previewAlt')}
          loading="lazy"
          onError={() => setBadPreview(true)}
          className="w-full bg-black"
        />
      ) : (
        <div className="flex h-16 items-center justify-center bg-surface-2 text-xs text-muted">
          {t('runs.noPreview')}
        </div>
      )}
      <div className="space-y-2 p-4">
        <div className="flex items-start gap-2">
          <span className="text-xs text-muted tabular-nums">#{rank}</span>
          {editing ? (
            <input
              value={hook}
              onChange={(e) => setHook(e.target.value)}
              aria-label={t('runs.hook')}
              className="h-8 flex-1 rounded-md border border-border bg-surface-2 px-2 text-sm font-semibold"
            />
          ) : (
            <h3 className="flex-1 text-sm font-semibold tracking-wide">{pick.hook}</h3>
          )}
          {pick.score != null && <Badge tone="accent">{Math.round(pick.score)}</Badge>}
        </div>
        {editing ? (
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            aria-label={t('runs.titleLabel')}
            className="h-8 w-full rounded-md border border-border bg-surface-2 px-2 text-sm"
          />
        ) : (
          <p className="text-sm">{pick.title}</p>
        )}
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          {editing ? (
            <>
              <input
                value={start}
                onChange={(e) => setStart(e.target.value)}
                aria-label={t('runs.start')}
                className="h-7 w-20 rounded-md border border-border bg-surface-2 px-2"
              />
              –
              <input
                value={end}
                onChange={(e) => setEnd(e.target.value)}
                aria-label={t('runs.end')}
                className="h-7 w-20 rounded-md border border-border bg-surface-2 px-2"
              />
            </>
          ) : (
            <span className="tabular-nums">
              {formatClock(part.start_s)} – {formatClock(part.end_s)} ·{' '}
              {Math.round(part.end_s - part.start_s)}s
            </span>
          )}
          {pick.credit && <span>· {pick.credit}</span>}
        </div>
        <p className="text-xs text-muted">{pick.hashtags.join(' ')}</p>
        {pick.ai_reason && <p className="text-xs italic text-muted">{pick.ai_reason}</p>}
        <RenderState pick={pick} />
        {(edit.error || render.error) && (
          <p className="text-xs text-danger">{(edit.error ?? render.error)?.message}</p>
        )}
        <div className="flex flex-wrap gap-1.5 pt-1">
          {/* After rendering, the next step is the review & customisation studio
              (downloads live there, after the user has seen the result). */}
          {v?.mp4_asset_id && pick.status !== 'rendering' && !editing && (
            <Link
              to={`/shorts/${pick.id}`}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-xs font-medium text-accent-fg hover:opacity-90"
            >
              <Palette size={14} aria-hidden /> {t('runs.customize')}
            </Link>
          )}
          {pick.status !== 'rendering' && !editing && (
            <Button
              size="sm"
              variant={v ? 'ghost' : 'primary'}
              onClick={() => render.mutate({ id: pick.id, body: renderBody })}
              disabled={render.isPending}
            >
              <Clapperboard size={14} aria-hidden /> {v ? t('render.again') : t('render.one')}
            </Button>
          )}
          {editing ? (
            <>
              <Button size="sm" onClick={save} disabled={edit.isPending}>
                <Check size={14} aria-hidden /> {t('runs.save')}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                <X size={14} aria-hidden /> {t('runs.cancel')}
              </Button>
            </>
          ) : (
            <>
              <Link
                to={`/sources/${pick.source_id}?t=${part.start_s.toFixed(1)}`}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs text-muted hover:bg-surface-2 hover:text-fg"
              >
                <ExternalLink size={14} aria-hidden /> {t('runs.watch')}
              </Link>
              <Link
                to={`/shorts/${pick.id}`}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs text-muted hover:bg-surface-2 hover:text-fg"
              >
                <SlidersHorizontal size={14} aria-hidden /> {t('runs.studio')}
              </Link>
              {editable && (
                <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
                  <Pencil size={14} aria-hidden /> {t('runs.edit')}
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => drop.mutate(pick.id)}
                disabled={drop.isPending}
              >
                <Trash2 size={14} aria-hidden /> {t('runs.drop')}
              </Button>
            </>
          )}
        </div>
      </div>
    </Card>
  )
}
