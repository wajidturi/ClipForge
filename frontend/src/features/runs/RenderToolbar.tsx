import { Clapperboard, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button, Card } from '@/components/ui'
import { TemplatePicker } from '@/features/studio/TemplatePicker'
import type { Aspect } from '@/lib/api/client'
import { renderBodyOf, type RenderChoice } from './renderChoice'
import { useRenderOptions, useRenderRun } from '@/lib/runs'

/** Step 2 of the one-click flow: choose a template, generate every pick. */
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

  return (
    <Card className="mb-6 space-y-4 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{t('tpl.choose')}</h2>
          <p className="text-xs text-muted">{t('tpl.chooseHelp')}</p>
        </div>
      </div>
      {opts.data && (
        <TemplatePicker
          value={value.template}
          onChange={(template) => onChange({ ...value, template })}
          templates={opts.data.templates}
          withAuto
        />
      )}
      <div className="flex flex-wrap items-end gap-4">
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
            onClick={() => renderAll.mutate(renderBodyOf(value))}
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
          {renderAll.error && (
            <span className="text-xs text-danger">{renderAll.error.message}</span>
          )}
        </div>
      </div>
    </Card>
  )
}
