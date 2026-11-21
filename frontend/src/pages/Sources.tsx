import { LibraryBig, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Card, CardHeader } from '@/components/ui'
import { AddSource } from '@/features/sources/AddSource'
import { SourceRow } from '@/features/sources/SourceRow'
import { usePlatforms, useSources } from '@/lib/sources'
import { PageHeader } from './Dashboard'

export function Sources() {
  const { t } = useTranslation()
  const sources = useSources()
  const platforms = usePlatforms()
  const [q, setQ] = useState('')

  const names = useMemo(() => {
    const m: Record<string, string> = { file: t('sources.uploaded'), other: t('sources.otherSite') }
    for (const p of platforms.data ?? []) m[p.id] = p.name
    return m
  }, [platforms.data, t])

  const items = (sources.data?.items ?? []).filter((s) => {
    const needle = q.trim().toLowerCase()
    return (
      !needle || `${s.title ?? ''} ${s.channel_name ?? ''} ${s.url}`.toLowerCase().includes(needle)
    )
  })

  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <PageHeader title={t('sources.title')} subtitle={t('sources.subtitle')} />
      <div className="grid gap-6">
        <AddSource />
        <Card>
          <CardHeader
            title={t('sources.library', { n: sources.data?.items.length ?? 0 })}
            action={
              <label className="relative">
                <Search
                  size={14}
                  className="absolute top-1/2 left-2.5 -translate-y-1/2 text-muted"
                  aria-hidden
                />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder={t('sources.search')}
                  aria-label={t('sources.search')}
                  className="h-8 w-56 rounded-md border border-border bg-surface-2 pr-2 pl-8 text-sm"
                />
              </label>
            }
          />
          {sources.isError && <p className="px-5 py-4 text-sm text-danger">{t('error.generic')}</p>}
          {items.length === 0 && !sources.isLoading ? (
            <div className="flex flex-col items-center gap-2 px-5 py-12 text-center text-sm text-muted">
              <LibraryBig size={22} aria-hidden />
              {q ? t('sources.noMatch') : t('sources.empty')}
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {items.map((s) => (
                <SourceRow key={s.id} src={s} platformName={names[s.platform] ?? s.platform} />
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}
