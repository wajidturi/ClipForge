import { CheckCircle2, Loader2, RotateCcw, Save, XCircle } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { Badge, Button, Card, CardHeader } from '@/components/ui'
import type { SettingField } from '@/lib/api/client'
import { useAIStatus } from '@/lib/runs'
import { useSaveSettings, useSettings } from '@/lib/settings'
import { cn } from '@/lib/utils'
import { PageHeader } from './Dashboard'

const SECTIONS = ['ai', 'analysis', 'render', 'sources'] as const
const AUTO = '__auto__'

function sameValue(a: unknown, b: unknown) {
  return JSON.stringify(a) === JSON.stringify(b)
}

export function SettingInput({
  field,
  value,
  onChange,
  models,
}: {
  field: SettingField
  value: unknown
  onChange: (v: unknown) => void
  models?: string[]
}) {
  const { t } = useTranslation()
  const id = `set-${field.key}`
  const cls = 'h-9 w-full rounded-lg border border-border bg-surface-2 px-3 text-sm'
  const optLabel = (c: unknown) =>
    t(`settings.choice.${field.key}.${String(c)}`, { defaultValue: String(c) })

  if (field.kind === 'bool')
    return (
      <input
        id={id}
        type="checkbox"
        checked={Boolean(value)}
        onChange={(e) => onChange(e.target.checked)}
        className="size-5 accent-accent"
      />
    )
  if (field.kind === 'int' || field.kind === 'float')
    return (
      <input
        id={id}
        type="number"
        value={value == null ? '' : String(value)}
        min={field.min ?? undefined}
        max={field.max ?? undefined}
        step={field.kind === 'int' ? 1 : 'any'}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        className={cn(cls, 'w-32')}
      />
    )
  if (field.kind === 'choice')
    return (
      <select
        id={id}
        value={value == null ? AUTO : String(value)}
        onChange={(e) => onChange(e.target.value === AUTO ? null : e.target.value)}
        className={cn(cls, 'w-64')}
      >
        {field.nullable && <option value={AUTO}>{t('settings.automatic')}</option>}
        {(field.choices ?? []).map((c) => (
          <option key={String(c)} value={String(c)}>
            {optLabel(c)}
          </option>
        ))}
      </select>
    )
  if (field.kind === 'list')
    return (
      <div className="flex flex-wrap gap-4">
        {(field.choices ?? []).map((c) => {
          const list = (value as unknown[] | null) ?? []
          return (
            <label key={String(c)} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4 accent-accent"
                checked={list.includes(c)}
                onChange={(e) =>
                  onChange(e.target.checked ? [...list, c] : list.filter((x) => x !== c))
                }
              />
              {optLabel(c)}
            </label>
          )
        })}
      </div>
    )
  return (
    <>
      <input
        id={id}
        value={value == null ? '' : String(value)}
        onChange={(e) => onChange(e.target.value === '' && field.nullable ? null : e.target.value)}
        list={models?.length ? `${id}-list` : undefined}
        placeholder={field.nullable ? t('settings.automatic') : undefined}
        className={cn(cls, 'max-w-md')}
      />
      {models?.length ? (
        <datalist id={`${id}-list`}>
          {models.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      ) : null}
    </>
  )
}

function AIStatusLine() {
  const ai = useAIStatus()
  if (!ai.data) return null
  const Icon = ai.data.ok ? CheckCircle2 : XCircle
  return (
    <p className={cn('flex items-center gap-2 text-xs', ai.data.ok ? 'text-ok' : 'text-warn')}>
      <Icon size={14} aria-hidden /> {ai.data.detail}
    </p>
  )
}

export function Settings() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const settings = useSettings()
  const save = useSaveSettings()
  const ai = useAIStatus()
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const fields = useMemo(() => settings.data ?? [], [settings.data])
  const byKey = useMemo(() => new Map(fields.map((f) => [f.key, f])), [fields])
  const changed = Object.entries(draft).filter(([k, v]) => !sameValue(v, byKey.get(k)?.value))
  const valueOf = (f: SettingField) => (f.key in draft ? draft[f.key] : f.value)

  const submit = () =>
    save.mutate(
      { values: Object.fromEntries(changed), reset: [] },
      { onSuccess: () => setDraft({}) },
    )
  const reset = (key: string) =>
    save.mutate(
      { values: {}, reset: [key] },
      {
        onSuccess: () =>
          setDraft((d) => {
            const n = { ...d }
            delete n[key]
            return n
          }),
      },
    )
  const errKey = (save.error as { message?: string } | null)?.message

  return (
    <div className="mx-auto max-w-4xl px-8 py-8 pb-28">
      <PageHeader title={t('settings.title')} subtitle={t('settings.subtitle')} />
      {settings.isLoading && <p className="text-sm text-muted">…</p>}
      <div className="space-y-6">
        {SECTIONS.map((sec) => {
          const list = fields.filter((f) => f.section === sec)
          if (!list.length) return null
          return (
            <Card key={sec}>
              <CardHeader
                title={t(`settings.section.${sec}`)}
                action={sec === 'ai' && <AIStatusLine />}
              />
              <div className="divide-y divide-border">
                {list.map((f) => {
                  const dirty = f.key in draft && !sameValue(draft[f.key], f.value)
                  return (
                    <div key={f.key} className="grid gap-2 px-5 py-4 sm:grid-cols-[16rem_1fr]">
                      <div>
                        <label htmlFor={`set-${f.key}`} className="text-sm font-medium">
                          {t(`settings.f.${f.key}.label`, { defaultValue: f.key })}
                        </label>
                        <p className="mt-0.5 text-xs text-muted">
                          {t(`settings.f.${f.key}.help`, { defaultValue: '' })}
                        </p>
                      </div>
                      <div className="flex min-w-0 flex-wrap items-center gap-3">
                        <SettingInput
                          field={f}
                          value={valueOf(f)}
                          onChange={(v) => setDraft((d) => ({ ...d, [f.key]: v }))}
                          models={f.key === 'ollama_model' ? ai.data?.models : undefined}
                        />
                        {dirty && <Badge tone="info">{t('settings.unsaved')}</Badge>}
                        {f.overridden && !dirty && (
                          <button
                            onClick={() => reset(f.key)}
                            className="inline-flex items-center gap-1 text-xs text-muted hover:text-fg"
                            title={t('settings.defaultIs', { v: JSON.stringify(f.default) })}
                          >
                            <RotateCcw size={12} aria-hidden /> {t('settings.reset')}
                          </button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </Card>
          )
        })}
        <Card className="flex flex-wrap items-center gap-4 p-5">
          <div className="flex-1">
            <p className="text-sm font-medium">{t('settings.setupTitle')}</p>
            <p className="text-xs text-muted">{t('settings.setupHelp')}</p>
          </div>
          <Button variant="secondary" onClick={() => navigate('/welcome')}>
            {t('settings.setupAgain')}
          </Button>
        </Card>
      </div>

      {changed.length > 0 && (
        <div className="fixed right-8 bottom-6 z-20 flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 shadow-xl">
          <span className="text-sm">{t('settings.changes', { n: changed.length })}</span>
          {errKey && <span className="max-w-xs text-xs text-danger">{errKey}</span>}
          <Button variant="ghost" size="sm" onClick={() => setDraft({})}>
            {t('runs.cancel')}
          </Button>
          <Button size="sm" onClick={submit} disabled={save.isPending}>
            {save.isPending ? (
              <Loader2 size={14} className="animate-spin" aria-hidden />
            ) : (
              <Save size={14} aria-hidden />
            )}
            {t('runs.save')}
          </Button>
        </div>
      )}
    </div>
  )
}
