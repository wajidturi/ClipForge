import { Clapperboard, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button, Card } from '@/components/ui'
import type { Aspect, Layout, RenderRequest } from '@/lib/api/client'
import { useRenderOptions, useRenderRun } from '@/lib/runs'

export type RenderChoice = { style: string; layout: Layout; aspects: Aspect[] }

export function RenderToolbar({
  runId,
  value,
  onChange,
  waiting,
}: {
  runId: string
  value: RenderChoice
  onChange: (v: RenderChoice) => void
  waiting: number
}) {
  const { t } = useTranslation()
  const opts = useRenderOptions()
  const renderAll = useRenderRun(runId)
  const body: RenderRequest = { style: value.style, layout: value.layout, aspects: value.aspects }
  const select = 'h-8 rounded-md border border-border bg-surface-2 px-2 text-sm'

  return (
    <Card className="mb-6 flex flex-wrap items-end gap-4 p-4">
      <label className="text-xs text-muted">
        {t('render.style')}
        <select
          className={`${select} mt-1 block`}
          value={value.style}
          onChange={(e) => onChange({ ...value, style: e.target.value })}
        >
          {opts.data?.styles.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
      <label className="text-xs text-muted">
        {t('render.layout')}
        <select
          className={`${select} mt-1 block`}
          value={value.layout}
          onChange={(e) => onChange({ ...value, layout: e.target.value as Layout })}
        >
          {opts.data?.layouts.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="text-xs text-muted">
        <legend>{t('render.extra')}</legend>
        <div className="mt-1.5 flex gap-3">
          {opts.data?.aspects.map((a) => (
            <label key={a.id} className="flex items-center gap-1.5 text-sm text-fg">
              <input
                type="checkbox"
                className="size-4 accent-accent"
                checked={value.aspects.includes(a.id as Aspect)}
                onChange={(e) =>
                  onChange({
                    ...value,
                    aspects: e.target.checked
                      ? [...value.aspects, a.id as Aspect]
                      : value.aspects.filter((x) => x !== a.id),
                  })
                }
              />
              {a.label}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="ml-auto flex flex-col items-end gap-1">
        <Button
          onClick={() => renderAll.mutate(body)}
          disabled={!waiting || renderAll.isPending}
          title={waiting ? undefined : t('render.nothing')}
        >
          {renderAll.isPending ? (
            <Loader2 size={14} className="animate-spin" aria-hidden />
          ) : (
            <Clapperboard size={14} aria-hidden />
          )}
          {t('render.all', { n: waiting })}
        </Button>
        {opts.data && (
          <span className="text-[11px] text-muted">
            {t('render.encoder', { e: opts.data.encoder })}
          </span>
        )}
        {renderAll.error && <span className="text-xs text-danger">{renderAll.error.message}</span>}
      </div>
    </Card>
  )
}
