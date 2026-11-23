/**
 * Studio tabs. Text edits save straight away (PATCH); anything that changes the
 * picture is applied by a new render, which creates a new version (old ones stay).
 */
import { Bot, Check, Clapperboard, EyeOff, Loader2, RotateCcw, Sparkles, X } from 'lucide-react'
import { useMemo, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge, Button } from '@/components/ui'
import type { ShortDetail, StudioWord } from '@/lib/api/client'
import {
  useApplyEdit,
  useEdits,
  usePatchShort,
  usePlanEdit,
  useRenderOne,
  useShortWords,
} from '@/lib/shorts'
import { cn, formatClock } from '@/lib/utils'

const input = 'h-9 w-full rounded-lg border border-border bg-surface-2 px-3 text-sm'

function Field({
  label,
  help,
  children,
}: {
  label: string
  help?: string
  children: React.ReactNode
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      {children}
      {help && <span className="mt-1 block text-xs text-muted">{help}</span>}
    </label>
  )
}

function ErrorLine({ error }: { error: Error | null }) {
  return error ? <p className="text-sm text-danger">{error.message}</p> : null
}

/** "Saved; render to see it in the video" + a render button. */
function RenderHint({ short, show }: { short: ShortDetail; show: boolean }) {
  const { t } = useTranslation()
  const render = useRenderOne(short.id)
  if (!show || !short.active || short.status === 'rendering') return null
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-info/40 bg-info/8 px-3 py-2 text-xs">
      <span className="flex-1">{t('studio.needsRender')}</span>
      <Button
        size="sm"
        onClick={() => render.mutate({ origin: 'manual_edit' })}
        disabled={render.isPending}
      >
        <Clapperboard size={13} aria-hidden /> {t('studio.renderNow')}
      </Button>
    </div>
  )
}

// ------------------------------------------------------------------ Post
export function PostTab({ short }: { short: ShortDetail }) {
  const { t } = useTranslation()
  const patch = usePatchShort(short.id)
  const [hook, setHook] = useState(short.hook ?? '')
  const [title, setTitle] = useState(short.title ?? '')
  const [tags, setTags] = useState(short.hashtags.join(' '))
  const [keywords, setKeywords] = useState(short.keywords.join(', '))
  const [picture, setPicture] = useState(false)

  const save = (e: FormEvent) => {
    e.preventDefault()
    const kw = keywords
      .split(',')
      .map((k) => k.trim())
      .filter(Boolean)
    const changesPicture =
      hook.trim().toUpperCase() !== (short.hook ?? '') ||
      kw.join(',').toUpperCase() !== short.keywords.join(',')
    patch.mutate(
      { hook, title, hashtags: tags.split(/[\s,]+/).filter(Boolean), keywords: kw },
      { onSuccess: () => setPicture(changesPicture) },
    )
  }

  return (
    <form onSubmit={save} className="space-y-4">
      <Field label={t('studio.post.hook')} help={t('studio.post.hookHelp')}>
        <input
          value={hook}
          onChange={(e) => setHook(e.target.value)}
          maxLength={120}
          className={input}
        />
      </Field>
      <Field label={t('studio.post.title')} help={t('studio.post.titleHelp', { n: title.length })}>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={200}
          className={input}
        />
      </Field>
      <Field label={t('studio.post.hashtags')} help={t('studio.post.hashtagsHelp')}>
        <input value={tags} onChange={(e) => setTags(e.target.value)} className={input} />
      </Field>
      <Field label={t('studio.post.keywords')} help={t('studio.post.keywordsHelp')}>
        <input value={keywords} onChange={(e) => setKeywords(e.target.value)} className={input} />
      </Field>
      <ErrorLine error={patch.error} />
      <Button type="submit" disabled={patch.isPending || short.status === 'rendering'}>
        {patch.isPending ? (
          <Loader2 size={14} className="animate-spin" aria-hidden />
        ) : (
          <Check size={14} aria-hidden />
        )}
        {t('runs.save')}
      </Button>
      {patch.isSuccess && !picture && (
        <span className="ml-3 text-xs text-ok">{t('studio.saved')}</span>
      )}
      <RenderHint short={short} show={picture} />
    </form>
  )
}

// ------------------------------------------------------------------ Trim
export function TrimTab({ short }: { short: ShortDetail }) {
  const { t } = useTranslation()
  const words = useShortWords(short.id)
  const patch = usePatchShort(short.id)
  const render = useRenderOne(short.id)
  const part = short.parts?.[0]
  const [range, setRange] = useState<[number, number] | null>(null)
  const scrolled = useRef(false)
  if (!part) return null
  const [a, b] = range ?? [part.start_s, part.end_s]
  const sents = words.data?.sentences ?? []
  const changed = range != null && (a !== part.start_s || b !== part.end_s)

  const save = (andRender: boolean) =>
    patch.mutate(
      { start_s: a, end_s: b },
      {
        onSuccess: () => {
          setRange(null)
          if (andRender && short.active) render.mutate({ origin: 'manual_edit' })
        },
      },
    )

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted">{t('studio.trim.help')}</p>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="tabular-nums">
          {formatClock(a)} – {formatClock(b)}
        </span>
        <Badge tone={b - a > 60 ? 'warn' : 'neutral'}>{Math.round(b - a)}s</Badge>
        {changed && (
          <span className="text-xs text-muted">
            {t('studio.trim.was', { from: formatClock(part.start_s), to: formatClock(part.end_s) })}
          </span>
        )}
      </div>
      <ol className="max-h-[26rem] space-y-0.5 overflow-y-auto rounded-lg border border-border p-1 text-sm">
        {words.isLoading && <li className="p-3 text-muted">…</li>}
        {sents.map((s, i) => {
          const inside = s.end > a + 0.05 && s.start < b - 0.05
          // open the list at the Short's first sentence, with a little context above
          const first = inside && !(i > 0 && sents[i - 1]!.end > a + 0.05)
          return (
            <li
              key={s.start}
              ref={
                first
                  ? (el) => {
                      if (el?.parentElement && !scrolled.current) {
                        el.parentElement.scrollTop = Math.max(0, el.offsetTop - 60)
                        scrolled.current = true
                      }
                    }
                  : undefined
              }
              className={cn(
                'group relative flex items-start gap-2 rounded-md px-2 py-1.5',
                inside ? 'bg-accent/10' : 'opacity-60 hover:opacity-100',
              )}
            >
              <span className="w-12 shrink-0 pt-0.5 text-xs text-muted tabular-nums">
                {formatClock(s.start)}
              </span>
              <span className="min-w-0 flex-1">{s.text}</span>
              <span className="absolute top-1 right-1 hidden gap-1 rounded-md bg-surface p-0.5 shadow-sm group-focus-within:flex group-hover:flex">
                <button
                  type="button"
                  className="rounded border border-border px-1.5 py-0.5 text-[11px] hover:bg-surface-2"
                  onClick={() => setRange([s.start, Math.max(b, s.end)])}
                >
                  {t('studio.trim.startHere')}
                </button>
                <button
                  type="button"
                  className="rounded border border-border px-1.5 py-0.5 text-[11px] hover:bg-surface-2"
                  onClick={() => setRange([Math.min(a, s.start), s.end])}
                >
                  {t('studio.trim.endHere')}
                </button>
              </span>
            </li>
          )
        })}
      </ol>
      <ErrorLine error={patch.error ?? render.error} />
      <div className="flex flex-wrap gap-2">
        {short.active ? (
          <Button
            onClick={() => save(true)}
            disabled={!changed || patch.isPending || short.status === 'rendering'}
          >
            <Clapperboard size={14} aria-hidden /> {t('studio.trim.saveRender')}
          </Button>
        ) : (
          <Button onClick={() => save(false)} disabled={!changed || patch.isPending}>
            <Check size={14} aria-hidden /> {t('runs.save')}
          </Button>
        )}
        {changed && (
          <Button variant="ghost" onClick={() => setRange(null)}>
            <RotateCcw size={14} aria-hidden /> {t('studio.undo')}
          </Button>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Captions
function WordChip({
  w,
  value,
  onChange,
}: {
  w: StudioWord
  value: string | undefined
  onChange: (v: string | undefined) => void
}) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const hidden = value === ''
  const shown = value ?? w.text
  if (editing)
    return (
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => setEditing(false)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            onChange(draft.trim() === w.text ? undefined : draft.trim())
            setEditing(false)
          } else if (e.key === 'Escape') setEditing(false)
        }}
        aria-label={t('studio.captions.editWord')}
        className="h-7 w-28 rounded border border-accent bg-surface px-1.5 text-sm"
      />
    )
  return (
    <span className="group inline-flex items-center">
      <button
        type="button"
        title={formatClock(w.start)}
        onClick={() => {
          setDraft(hidden ? w.text : shown)
          setEditing(true)
        }}
        className={cn(
          'rounded px-1 py-0.5 text-sm hover:bg-surface-2',
          value !== undefined && !hidden && 'bg-accent/15 text-accent',
          hidden && 'text-muted line-through',
        )}
      >
        {hidden ? w.text : shown}
      </button>
      {value !== undefined ? (
        <button
          type="button"
          onClick={() => onChange(undefined)}
          aria-label={t('studio.captions.restore')}
          className="hidden rounded p-0.5 text-muted group-hover:inline hover:text-fg"
        >
          <RotateCcw size={11} />
        </button>
      ) : (
        <button
          type="button"
          onClick={() => onChange('')}
          aria-label={t('studio.captions.hide')}
          className="hidden rounded p-0.5 text-muted group-hover:inline hover:text-fg"
        >
          <EyeOff size={11} />
        </button>
      )}
    </span>
  )
}

export function CaptionsTab({ short }: { short: ShortDetail }) {
  const { t } = useTranslation()
  const words = useShortWords(short.id)
  const render = useRenderOne(short.id)
  const saved = words.data?.overrides
  const [draft, setDraft] = useState<Record<string, string> | null>(null) // null = unchanged
  const overrides = draft ?? saved ?? {}
  const dirty = JSON.stringify(overrides) !== JSON.stringify(saved ?? {})
  const fixes = Object.keys(overrides).length

  const set = (key: string, v: string | undefined) =>
    setDraft(() => {
      const n = { ...overrides }
      if (v === undefined) delete n[key]
      else n[key] = v
      return n
    })

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted">{t('studio.captions.help')}</p>
      <div className="max-h-[26rem] overflow-y-auto rounded-lg border border-border p-3 leading-8">
        {words.isLoading && <span className="text-muted">…</span>}
        {words.data?.words.map((w) => (
          <span key={w.key}>
            <WordChip w={w} value={overrides[w.key]} onChange={(v) => set(w.key, v)} />{' '}
          </span>
        ))}
      </div>
      <ErrorLine error={render.error} />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          onClick={() =>
            render.mutate(
              { caption_overrides: overrides, origin: 'manual_edit' },
              { onSuccess: () => setDraft(null) },
            )
          }
          disabled={!dirty || render.isPending || short.status === 'rendering'}
        >
          <Clapperboard size={14} aria-hidden /> {t('studio.captions.render', { n: fixes })}
        </Button>
        {dirty && (
          <Button variant="ghost" onClick={() => setDraft(null)}>
            <RotateCcw size={14} aria-hidden /> {t('studio.undo')}
          </Button>
        )}
        {!dirty && fixes > 0 && (
          <span className="text-xs text-muted">{t('studio.captions.active', { n: fixes })}</span>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ AI edit
const IDEAS = ['punchier', 'later', 'shorter', 'karaoke', 'title'] as const

type Op = {
  op: string
  text?: string
  style?: string
  layout?: string
  words?: string[]
  start_delta_s?: number
  end_delta_s?: number
  wrong?: string
  right?: string
}

function OpLine({ op }: { op: Op }) {
  const { t } = useTranslation()
  let value = op.text ?? op.style ?? op.layout ?? op.words?.join(' ') ?? ''
  if (op.op === 'trim') {
    const bits = []
    if (op.start_delta_s)
      bits.push(
        t('studio.ai.start', {
          s: op.start_delta_s > 0 ? `+${op.start_delta_s}` : op.start_delta_s,
        }),
      )
    if (op.end_delta_s)
      bits.push(
        t('studio.ai.end', { s: op.end_delta_s > 0 ? `+${op.end_delta_s}` : op.end_delta_s }),
      )
    value = bits.join(', ')
  } else if (op.op === 'fix_word') value = `${op.wrong} → ${op.right || '∅'}`
  return (
    <li className="flex gap-2">
      <Badge tone="accent">{t(`studio.ai.op.${op.op}`, { defaultValue: op.op })}</Badge>
      <span className="min-w-0 flex-1 break-words">{value}</span>
    </li>
  )
}

export function AIEditTab({ short }: { short: ShortDetail }) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const planEdit = usePlanEdit(short.id)
  const apply = useApplyEdit(short.id)
  const edits = useEdits(short.id)
  const plan = planEdit.data
  const history = useMemo(
    () => (edits.data ?? []).filter((e) => e.id !== plan?.id),
    [edits.data, plan],
  )

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (text.trim().length >= 2) planEdit.mutate(text.trim())
  }

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="space-y-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit(e)
          }}
          rows={3}
          maxLength={2000}
          placeholder={t('studio.ai.placeholder')}
          aria-label={t('studio.ai.instruction')}
          className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm"
        />
        <div className="flex flex-wrap gap-1.5">
          {IDEAS.map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setText(t(`studio.ai.ideas.${k}`))}
              className="rounded-full border border-border px-2.5 py-1 text-xs text-muted hover:bg-surface-2 hover:text-fg"
            >
              {t(`studio.ai.ideas.${k}`)}
            </button>
          ))}
        </div>
        <Button
          type="submit"
          disabled={planEdit.isPending || text.trim().length < 2 || short.status === 'rendering'}
        >
          {planEdit.isPending ? (
            <Loader2 size={14} className="animate-spin" aria-hidden />
          ) : (
            <Bot size={14} aria-hidden />
          )}
          {planEdit.isPending ? t('studio.ai.thinking') : t('studio.ai.plan')}
        </Button>
      </form>
      <ErrorLine error={planEdit.error ?? apply.error} />

      {plan && (
        <div
          className={cn(
            'space-y-3 rounded-lg border p-4 text-sm',
            plan.status === 'failed' ? 'border-warn/40 bg-warn/5' : 'border-accent/40 bg-accent/5',
          )}
          data-testid="edit-plan"
        >
          <p className="flex items-start gap-2">
            <Sparkles size={15} className="mt-0.5 shrink-0 text-accent" aria-hidden />
            {plan.status === 'failed' ? plan.error : String(plan.plan.summary ?? '')}
          </p>
          {plan.status !== 'failed' && (
            <ul className="space-y-1.5">
              {((plan.plan.ops as Op[] | undefined) ?? []).map((op, i) => (
                <OpLine key={i} op={op} />
              ))}
            </ul>
          )}
          {((plan.plan.notes as string[] | undefined) ?? []).map((n, i) => (
            <p key={i} className="text-xs text-warn">
              {n}
            </p>
          ))}
          {plan.status === 'planned' && !apply.isSuccess && (
            <div className="flex gap-2">
              <Button size="sm" onClick={() => apply.mutate(plan.id)} disabled={apply.isPending}>
                <Check size={14} aria-hidden /> {t('studio.ai.apply')}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => planEdit.reset()}>
                <X size={14} aria-hidden /> {t('studio.ai.discard')}
              </Button>
            </div>
          )}
          {apply.isSuccess && (
            <p className="text-xs text-ok">
              {apply.data.job_id ? t('studio.ai.rendering') : t('studio.ai.appliedText')}
            </p>
          )}
        </div>
      )}

      {history.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-medium text-muted">{t('studio.ai.history')}</h3>
          <ul className="divide-y divide-border rounded-lg border border-border text-xs">
            {history.map((e) => (
              <li key={e.id} className="flex items-center gap-2 px-3 py-2">
                <span className="min-w-0 flex-1 truncate">{e.instruction}</span>
                <Badge
                  tone={
                    e.status === 'applied' ? 'ok' : e.status === 'failed' ? 'danger' : 'neutral'
                  }
                >
                  {t(`studio.ai.status.${e.status}`, { defaultValue: e.status })}
                </Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
