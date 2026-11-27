import { Bot, CheckCircle2, Clock, Film, Loader2, Sparkles, Wand2, XCircle } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import { Badge, Button, Card, CardHeader } from '@/components/ui'
import { TemplatePicker } from '@/features/studio/TemplatePicker'
import type { PickMode, TemplateChoice } from '@/lib/api/client'
import { useAIStatus, useCreateRun, useRenderOptions, useRuns } from '@/lib/runs'
import { useSources } from '@/lib/sources'
import { cn, formatClock } from '@/lib/utils'
import { PageHeader } from './Dashboard'

const MODES: PickMode[] = ['smart', 'deep', 'free', 'whole']
const LENGTHS = ['short', 'medium', 'long'] as const
type Length = (typeof LENGTHS)[number]
const MAX_SHORTS = 50

function AIStatusLine() {
  const ai = useAIStatus()
  if (!ai.data) return null
  const Icon = ai.data.ok ? CheckCircle2 : XCircle
  return (
    <p className={cn('flex items-center gap-2 text-xs', ai.data.ok ? 'text-ok' : 'text-warn')}>
      <Icon size={14} aria-hidden />
      {ai.data.detail}
    </p>
  )
}

export function Create() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const sources = useSources()
  const runs = useRuns()
  const create = useCreateRun()
  const ready = (sources.data?.items ?? []).filter((s) => s.status === 'ready')
  const [picked, setPicked] = useState<string[]>([])
  const [n, setN] = useState(5)
  const [mode, setMode] = useState<PickMode>('smart')
  const [topic, setTopic] = useState('')
  const [length, setLength] = useState<Length>('short')
  const [template, setTemplate] = useState<TemplateChoice>('auto')
  const [autoRender, setAutoRender] = useState(true)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const opts = useRenderOptions()

  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))

  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate(
      {
        source_ids: picked,
        n,
        pick_mode: mode,
        topic: topic.trim() || null,
        length,
        render: autoRender ? { template, aspects: [] } : null,
        start: from.trim() || null,
        end: to.trim() || null,
      },
      { onSuccess: (run) => navigate(`/runs/${run.id}`) },
    )
  }

  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <PageHeader title={t('create.title')} subtitle={t('create.subtitle')} />
      <form onSubmit={submit} className="grid gap-6">
        <Card>
          <CardHeader
            title={t('create.sources', { n: picked.length })}
            action={
              ready.length > 0 && (
                <button
                  type="button"
                  className="text-xs text-accent hover:underline"
                  onClick={() => setPicked(picked.length ? [] : ready.map((s) => s.id))}
                >
                  {picked.length ? t('create.none') : t('create.all')}
                </button>
              )
            }
          />
          {ready.length === 0 ? (
            <p className="px-5 py-6 text-sm text-muted">
              {t('create.noSources')}{' '}
              <Link to="/sources" className="text-accent hover:underline">
                {t('nav.sources')}
              </Link>
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {ready.map((s) => (
                <li key={s.id}>
                  <label className="flex cursor-pointer items-center gap-3 px-5 py-3 text-sm hover:bg-surface-2">
                    <input
                      type="checkbox"
                      checked={picked.includes(s.id)}
                      onChange={() => toggle(s.id)}
                      className="size-4 accent-accent"
                    />
                    <span className="min-w-0 flex-1 truncate">{s.title ?? s.url}</span>
                    <span className="text-xs text-muted">
                      {[s.channel_name, formatClock(s.duration_s)].filter(Boolean).join(' · ')}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="space-y-5 p-5">
          <div>
            <p className="mb-2 text-sm font-medium">{t('create.mode')}</p>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4" role="radiogroup">
              {MODES.map((m) => (
                <button
                  type="button"
                  role="radio"
                  aria-checked={mode === m}
                  key={m}
                  onClick={() => setMode(m)}
                  className={cn(
                    'rounded-lg border p-3 text-left text-sm transition',
                    mode === m ? 'border-accent bg-accent/8' : 'border-border hover:bg-surface-2',
                  )}
                >
                  <span className="flex items-center gap-2 font-medium">
                    {m === 'free' ? (
                      <Sparkles size={14} aria-hidden />
                    ) : m === 'whole' ? (
                      <Film size={14} aria-hidden />
                    ) : (
                      <Bot size={14} aria-hidden />
                    )}
                    {t(`create.modes.${m}.name`)}
                  </span>
                  <span className="mt-1 block text-xs text-muted">
                    {t(`create.modes.${m}.help`)}
                  </span>
                </button>
              ))}
            </div>
            {(mode === 'smart' || mode === 'deep') && (
              <div className="mt-2">
                <AIStatusLine />
              </div>
            )}
          </div>
          <div className="flex flex-wrap gap-6">
            {mode !== 'whole' && (
              <label className="text-sm">
                <span className="mb-1 block font-medium">{t('create.count')}</span>
                <input
                  type="number"
                  min={1}
                  max={MAX_SHORTS}
                  value={n}
                  onChange={(e) =>
                    setN(Math.max(1, Math.min(MAX_SHORTS, Number(e.target.value) || 1)))
                  }
                  className="h-9 w-24 rounded-lg border border-border bg-surface-2 px-3"
                />
              </label>
            )}
            {mode !== 'whole' && (
              <div className="text-sm">
                <span className="mb-1 block font-medium">{t('create.length')}</span>
                <div
                  role="radiogroup"
                  aria-label={t('create.length')}
                  className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5"
                >
                  {LENGTHS.map((l) => (
                    <button
                      key={l}
                      type="button"
                      role="radio"
                      aria-checked={length === l}
                      onClick={() => setLength(l)}
                      className={cn(
                        'h-8 rounded-md px-3 transition',
                        length === l ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg',
                      )}
                    >
                      {t(`create.lengths.${l}.name`)}
                    </button>
                  ))}
                </div>
                <span className="mt-1 block text-xs text-muted">
                  {t(`create.lengths.${length}.help`)}
                </span>
              </div>
            )}
            <label className="min-w-60 flex-1 text-sm">
              <span className="mb-1 block font-medium">{t('create.topic')}</span>
              <input
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder={t('create.topicPh')}
                maxLength={200}
                className="h-9 w-full rounded-lg border border-border bg-surface-2 px-3"
              />
            </label>
          </div>
          <fieldset className="text-sm">
            <legend className="mb-1 flex items-center gap-2 font-medium">
              <Clock size={14} aria-hidden /> {t('create.range')}
            </legend>
            <div className="flex flex-wrap items-center gap-2">
              <input
                aria-label={t('create.rangeFrom')}
                placeholder={t('create.rangeFromPh')}
                value={from}
                onChange={(e) => setFrom(e.target.value)}
                className="h-9 w-28 rounded-lg border border-border bg-surface-2 px-3"
              />
              <span className="text-muted">–</span>
              <input
                aria-label={t('create.rangeTo')}
                placeholder={t('create.rangeToPh')}
                value={to}
                onChange={(e) => setTo(e.target.value)}
                className="h-9 w-28 rounded-lg border border-border bg-surface-2 px-3"
              />
              {(from || to) && (
                <button
                  type="button"
                  className="text-xs text-accent hover:underline"
                  onClick={() => {
                    setFrom('')
                    setTo('')
                  }}
                >
                  {t('create.rangeClear')}
                </button>
              )}
            </div>
            <span className="mt-1 block text-xs text-muted">{t('create.rangeHelp')}</span>
          </fieldset>
          <div className="space-y-3 border-t border-border pt-5">
            <label className="flex items-center gap-3 text-sm font-medium">
              <input
                type="checkbox"
                checked={autoRender}
                onChange={(e) => setAutoRender(e.target.checked)}
                className="size-4 accent-accent"
              />
              <Wand2 size={15} className="text-accent" aria-hidden />
              {t('create.autoRender')}
            </label>
            {autoRender && opts.data && (
              <>
                <p className="text-xs text-muted">{t('create.templateHelp')}</p>
                <TemplatePicker
                  value={template}
                  onChange={setTemplate}
                  templates={opts.data.templates}
                  withAuto
                />
              </>
            )}
          </div>
          {create.error && (
            <p role="alert" className="text-sm text-danger">
              {create.error.message}
            </p>
          )}
          <Button type="submit" disabled={!picked.length || create.isPending}>
            {create.isPending && <Loader2 size={14} className="animate-spin" aria-hidden />}
            {mode === 'whole'
              ? t('create.startWhole', { count: picked.length })
              : autoRender
                ? t('create.startRender', { n })
                : t('create.start', { n })}
          </Button>
        </Card>
      </form>

      {(runs.data?.length ?? 0) > 0 && (
        <Card className="mt-6">
          <CardHeader title={t('create.recent')} />
          <ul className="divide-y divide-border text-sm">
            {runs.data!.map((r) => (
              <li key={r.id}>
                <Link
                  to={`/runs/${r.id}`}
                  className="flex items-center gap-3 px-5 py-3 hover:bg-surface-2"
                >
                  <span className="flex-1">
                    {t('create.runLine', {
                      n: Number(r.params.n),
                      mode: t(`create.modes.${String(r.params.pick_mode)}.name`),
                    })}
                  </span>
                  <span className="text-xs text-muted">
                    {new Date(r.created_at).toLocaleString()}
                  </span>
                  <Badge
                    tone={
                      r.status === 'succeeded' ? 'ok' : r.status === 'failed' ? 'danger' : 'info'
                    }
                  >
                    {t(`runs.status.${r.status}`)}
                  </Badge>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
