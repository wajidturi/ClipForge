import { Construction } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { PageHeader } from './Dashboard'

export function Placeholder({ navKey, phase }: { navKey: string; phase: number }) {
  const { t } = useTranslation()
  const page = t(`nav.${navKey}`)
  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <PageHeader title={t('placeholder.title', { page })} />
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-sm text-muted">
        <Construction size={24} aria-hidden />
        {t('placeholder.body', { phase })}
      </div>
    </div>
  )
}
