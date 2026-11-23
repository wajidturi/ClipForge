import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  Loader2,
  Sparkles,
  XCircle,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { Button, Card } from '@/components/ui'
import { AddSource } from '@/features/sources/AddSource'
import { api, unwrap } from '@/lib/api/client'
import { useAIStatus } from '@/lib/runs'
import { settingValue, useSaveSettings, useSettings } from '@/lib/settings'
import { cn } from '@/lib/utils'

const STEPS = ['system', 'ai', 'source'] as const

function SystemStep() {
  const { t } = useTranslation()
  const doc = useQuery({
    queryKey: ['doctor'],
    queryFn: async () => unwrap(await api.GET('/api/v1/system/doctor')),
  })
  return (
    <div className="space-y-4">
      <ul className="space-y-1.5 text-sm text-muted">
        <li>• {t('welcome.what1')}</li>
        <li>• {t('welcome.what2')}</li>
        <li>• {t('welcome.what3')}</li>
      </ul>
      <h3 className="pt-2 text-sm font-medium">{t('welcome.check')}</h3>
      {doc.isLoading && <Loader2 size={16} className="animate-spin text-muted" aria-hidden />}
      <ul className="space-y-2">
        {doc.data?.checks.map((c) => (
          <li key={c.name} className="flex gap-2 text-sm">
            {c.ok ? (
              <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-ok" aria-hidden />
            ) : c.required ? (
              <XCircle size={16} className="mt-0.5 shrink-0 text-danger" aria-hidden />
            ) : (
              <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden />
            )}
            <div>
              <span className="font-medium">{c.name}</span>{' '}
              <span className="text-muted">{c.detail}</span>
              {!c.ok && c.fix && <p className="text-xs text-muted">{c.fix}</p>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function AIStep() {
  const { t } = useTranslation()
  const settings = useSettings()
  const save = useSaveSettings()
  const ai = useAIStatus()
  const provider = settingValue<string>(settings.data, 'ai_provider') ?? 'ollama'
  const model = settingValue<string>(settings.data, 'ollama_model') ?? ''
  const [typed, setM] = useState<string | null>(null) // null = show the saved model
  const m = typed ?? model

  const choice = (value: 'ollama' | 'none', icon: typeof Bot) => {
    const Icon = icon
    return (
      <button
        type="button"
        role="radio"
        aria-checked={provider === value}
        onClick={() => save.mutate({ values: { ai_provider: value }, reset: [] })}
        className={cn(
          'flex-1 rounded-lg border p-4 text-left text-sm transition',
          provider === value ? 'border-accent bg-accent/8' : 'border-border hover:bg-surface-2',
        )}
      >
        <span className="flex items-center gap-2 font-medium">
          <Icon size={15} aria-hidden /> {t(`welcome.ai.${value}.name`)}
        </span>
        <span className="mt-1 block text-xs text-muted">{t(`welcome.ai.${value}.help`)}</span>
      </button>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row" role="radiogroup">
        {choice('ollama', Bot)}
        {choice('none', Sparkles)}
      </div>
      {provider === 'ollama' && (
        <div className="space-y-3">
          {ai.data && (
            <p
              className={cn(
                'flex items-center gap-2 text-xs',
                ai.data.ok ? 'text-ok' : 'text-warn',
              )}
            >
              {ai.data.ok ? <CheckCircle2 size={14} /> : <XCircle size={14} />} {ai.data.detail}
            </p>
          )}
          <label className="block text-sm">
            <span className="mb-1 block font-medium">{t('settings.f.ollama_model.label')}</span>
            <div className="flex gap-2">
              <input
                value={m}
                onChange={(e) => setM(e.target.value)}
                list="welcome-models"
                className="h-9 w-64 rounded-lg border border-border bg-surface-2 px-3 text-sm"
              />
              <datalist id="welcome-models">
                {ai.data?.models.map((x) => (
                  <option key={x} value={x} />
                ))}
              </datalist>
              <Button
                variant="secondary"
                onClick={() => save.mutate({ values: { ollama_model: m }, reset: [] })}
                disabled={!m.trim() || m === model || save.isPending}
              >
                {t('runs.save')}
              </Button>
            </div>
            <span className="mt-1 block text-xs text-muted">{t('welcome.ai.modelHelp')}</span>
          </label>
        </div>
      )}
      {save.error && <p className="text-sm text-danger">{save.error.message}</p>}
    </div>
  )
}

/** First-run setup: system check -> AI choice -> first source. Can be re-run from Settings. */
export function Welcome() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const save = useSaveSettings()
  const finish = (to: string) =>
    save.mutate({ values: { onboarded: true }, reset: [] }, { onSuccess: () => navigate(to) })
  const key = STEPS[step]!

  return (
    <div className="flex min-h-full items-start justify-center bg-bg px-6 py-12">
      <div className="w-full max-w-2xl">
        <div className="mb-6 flex items-center gap-3">
          <img src="/favicon.svg" alt="" className="size-8" />
          <div>
            <h1 className="text-xl font-semibold tracking-tight">{t('welcome.title')}</h1>
            <p className="text-sm text-muted">{t('welcome.subtitle')}</p>
          </div>
        </div>
        <ol className="mb-4 flex gap-2" aria-label={t('welcome.steps')}>
          {STEPS.map((s, i) => (
            <li
              key={s}
              aria-current={i === step ? 'step' : undefined}
              className={cn(
                'flex-1 rounded-full py-1 text-center text-xs',
                i === step
                  ? 'bg-accent text-accent-fg'
                  : i < step
                    ? 'bg-accent/20 text-accent'
                    : 'bg-surface-2 text-muted',
              )}
            >
              {i + 1}. {t(`welcome.step.${s}`)}
            </li>
          ))}
        </ol>
        <Card className="p-6">
          <h2 className="mb-4 text-base font-semibold">{t(`welcome.head.${key}`)}</h2>
          {key === 'system' && <SystemStep />}
          {key === 'ai' && <AIStep />}
          {key === 'source' && (
            <div className="space-y-3">
              <p className="text-sm text-muted">{t('welcome.sourceHelp')}</p>
              <AddSource />
            </div>
          )}
          {save.error && <p className="mt-3 text-sm text-danger">{save.error.message}</p>}
          <div className="mt-6 flex items-center gap-2 border-t border-border pt-4">
            {step > 0 && (
              <Button variant="ghost" onClick={() => setStep(step - 1)}>
                {t('welcome.back')}
              </Button>
            )}
            <button
              onClick={() => finish('/')}
              className="text-xs text-muted hover:text-fg"
              disabled={save.isPending}
            >
              {t('welcome.skip')}
            </button>
            <div className="flex-1" />
            {step < STEPS.length - 1 ? (
              <Button onClick={() => setStep(step + 1)}>
                {t('welcome.next')} <ArrowRight size={14} aria-hidden />
              </Button>
            ) : (
              <Button onClick={() => finish('/sources')} disabled={save.isPending}>
                {t('welcome.finish')} <ArrowRight size={14} aria-hidden />
              </Button>
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}
