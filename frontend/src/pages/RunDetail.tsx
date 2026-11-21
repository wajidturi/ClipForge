import { AlertTriangle, ArrowLeft } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import { Badge, Card, CardHeader, Progress } from '@/components/ui'
import { useState } from 'react'
import { PickCard } from '@/features/runs/PickCard'
import { RenderToolbar, type RenderChoice } from '@/features/runs/RenderToolbar'
import { useJob } from '@/lib/jobs'
import { useRun } from '@/lib/runs'
import { formatClock } from '@/lib/utils'

type Rejected = { start: number; end: number; hook: string; issues: string[] }
type Callback = {
  setup_start: number
  setup_text: string
  payoff_start: number
  payoff_text: string
  gap_s: number
}

export function RunDetail() {
  const { t } = useTranslation()
  const { id = '' } = useParams()
  const run = useRun(id)
  const r = run.data
  const busy = r?.status === 'queued' || r?.status === 'running'
  const job = useJob(busy ? r?.job_id : null)
  const [choice, setChoice] = useState<RenderChoice>({
    style: 'classic',
    layout: 'auto',
    aspects: [],
  })
  const renderBody = { style: choice.style, layout: choice.layout, aspects: choice.aspects }

  if (run.isError) return <p className="px-8 py-8 text-sm text-danger">{t('runs.notFound')}</p>
  if (!r) return <p className="px-8 py-8 text-sm text-muted">…</p>

  const result = r.result as {
    warnings?: string[]
    rejected?: Rejected[]
    callbacks?: Callback[]
    candidates?: number
  }
  const usage = r.ai_usage as {
    model?: string
    input_tokens?: number
    output_tokens?: number
    seconds?: number
  }

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <Link
        to="/create"
        className="mb-4 inline-flex items-center gap-1 text-xs text-muted hover:text-fg"
      >
        <ArrowLeft size={13} aria-hidden /> {t('nav.create')}
      </Link>
      <header className="mb-6 flex items-start gap-4">
        <div className="flex-1">
          <h1 className="text-xl font-semibold tracking-tight">
            {t('runs.title', { n: Number(r.params.n) })}
          </h1>
          <p className="mt-1 text-sm text-muted">
            {[
              t(`create.modes.${String(r.params.pick_mode)}.name`),
              r.ai_model,
              r.params.topic ? `${t('create.topic')}: ${String(r.params.topic)}` : null,
              usage.seconds ? `${Math.round(usage.seconds)}s` : null,
              usage.input_tokens
                ? `${usage.input_tokens + (usage.output_tokens ?? 0)} tokens`
                : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        <Badge tone={r.status === 'succeeded' ? 'ok' : r.status === 'failed' ? 'danger' : 'info'}>
          {t(`runs.status.${r.status}`)}
        </Badge>
      </header>

      {busy && (
        <Card className="mb-6 p-5">
          <Progress value={job.data?.progress ?? 0} />
          <p className="mt-2 text-sm text-muted">{job.data?.step ?? t('runs.status.queued')}</p>
        </Card>
      )}
      {r.error && (
        <Card className="mb-6 flex gap-2 border-danger/40 p-4 text-sm text-danger">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden /> {r.error}
        </Card>
      )}
      {(result.warnings?.length ?? 0) > 0 && (
        <ul className="mb-6 space-y-1 rounded-xl border border-warn/40 bg-warn/5 px-4 py-3 text-xs text-warn">
          {result.warnings!.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}

      {r.status === 'succeeded' && r.shorts.length === 0 && (
        <p className="text-sm text-muted">{t('runs.empty')}</p>
      )}
      {r.shorts.length > 0 && (
        <RenderToolbar
          runId={r.id}
          value={choice}
          onChange={setChoice}
          waiting={r.shorts.filter((s) => s.status === 'picked').length}
        />
      )}
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {r.shorts.map((s, i) => (
          <PickCard key={s.id} pick={s} runId={r.id} rank={i + 1} renderBody={renderBody} />
        ))}
      </div>

      {(result.callbacks?.length ?? 0) > 0 && (
        <Card className="mt-6">
          <CardHeader title={t('runs.callbacks')} />
          <ul className="divide-y divide-border text-xs">
            {result.callbacks!.map((c, i) => (
              <li key={i} className="px-5 py-3">
                <p>
                  <span className="text-muted">{formatClock(c.setup_start)}</span> “{c.setup_text}”
                </p>
                <p className="mt-1">
                  <span className="text-muted">
                    +{Math.round(c.gap_s / 60)} min · {formatClock(c.payoff_start)}
                  </span>{' '}
                  “{c.payoff_text}”
                </p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {(result.rejected?.length ?? 0) > 0 && (
        <details className="mt-6 rounded-xl border border-border bg-surface">
          <summary className="cursor-pointer px-5 py-3 text-sm font-medium">
            {t('runs.rejected', { n: result.rejected!.length })}
          </summary>
          <ul className="divide-y divide-border border-t border-border text-xs">
            {result.rejected!.map((x, i) => (
              <li key={i} className="px-5 py-2">
                <span className="text-muted tabular-nums">
                  {formatClock(x.start)}–{formatClock(x.end)}
                </span>{' '}
                {x.hook} — <span className="text-warn">{x.issues.join('; ')}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {r.candidates.length > 0 && (
        <details className="mt-4 rounded-xl border border-border bg-surface">
          <summary className="cursor-pointer px-5 py-3 text-sm font-medium">
            {t('runs.candidates', { n: r.candidates.length })}
          </summary>
          <ol className="divide-y divide-border border-t border-border text-xs">
            {r.candidates.map((c) => (
              <li key={c.rank} className="flex gap-3 px-5 py-2">
                <span className="w-6 text-muted">{c.rank}</span>
                <span className="w-24 text-muted tabular-nums">
                  {formatClock(c.start_s)}–{formatClock(c.end_s)}
                </span>
                <span className="w-10 tabular-nums">{Math.round(c.score)}</span>
                <span className="w-32 text-muted">{c.tags.join(' ')}</span>
                <span className="min-w-0 flex-1 truncate">{c.head_text}</span>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  )
}
