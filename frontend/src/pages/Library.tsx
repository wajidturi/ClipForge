import { Check, Loader2, Search, Trash2, X } from 'lucide-react'
import { useDeferredValue, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'
import { Button, Card } from '@/components/ui'
import { DeleteShortsDialog } from '@/features/shorts/DeleteShorts'
import { ShortTile } from '@/features/shorts/ShortTile'
import type { ShortStatus } from '@/lib/api/client'
import { useBulkReview, useShorts, type LibraryFilter } from '@/lib/shorts'
import { cn } from '@/lib/utils'
import { PageHeader } from './Dashboard'

const TABS: { key: string; status?: ShortStatus[] }[] = [
  { key: 'all' },
  { key: 'review', status: ['review'] },
  { key: 'approved', status: ['approved'] },
  { key: 'picked', status: ['picked', 'rendering'] },
  { key: 'rejected', status: ['rejected'] },
  { key: 'failed', status: ['failed'] },
]
const QC = ['pass', 'warn', 'fail'] as const

export function Library() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const tab = TABS.find((x) => x.key === params.get('tab')) ?? TABS[0]!
  const qc = (QC as readonly string[]).includes(params.get('qc') ?? '')
    ? (params.get('qc') as LibraryFilter['qc'])
    : undefined
  const [q, setQ] = useState('')
  const deferredQ = useDeferredValue(q)
  const filter = useMemo<LibraryFilter>(
    () => ({ status: tab.status, qc, q: deferredQ || undefined }),
    [tab, qc, deferredQ],
  )
  const shorts = useShorts(filter)
  const items = shorts.data?.pages.flatMap((p) => p.items) ?? []
  const total = shorts.data?.pages[0]?.total ?? 0
  const [selected, setSelected] = useState<string[]>([])
  const bulk = useBulkReview()
  const [toDelete, setToDelete] = useState<{ ids: string[]; name?: string | null }>({ ids: [] })

  const setParam = (k: string, v: string | null) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v)
    else next.delete(k)
    setParams(next, { replace: true })
    setSelected([])
  }
  const toggle = (id: string) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))
  const act = (action: 'approve' | 'reject') =>
    bulk.mutate({ ids: selected, action }, { onSuccess: () => setSelected([]) })

  return (
    <div className="mx-auto max-w-7xl px-8 py-8">
      <PageHeader title={t('shorts.title')} subtitle={t('shorts.subtitle')} />
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1 rounded-lg bg-surface-2 p-1" role="tablist">
          {TABS.map((x) => (
            <button
              key={x.key}
              role="tab"
              aria-selected={x.key === tab.key}
              onClick={() => setParam('tab', x.key === 'all' ? null : x.key)}
              className={cn(
                'rounded-md px-3 py-1.5 text-xs font-medium transition',
                x.key === tab.key ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg',
              )}
            >
              {t(`shorts.tabs.${x.key}`)}
            </button>
          ))}
        </div>
        <select
          value={qc ?? ''}
          onChange={(e) => setParam('qc', e.target.value || null)}
          aria-label={t('shorts.qcFilter')}
          className="h-8 rounded-md border border-border bg-surface-2 px-2 text-xs"
        >
          <option value="">{t('shorts.qcAny')}</option>
          {QC.map((v) => (
            <option key={v} value={v}>
              QC {t(`render.qc.${v}`)}
            </option>
          ))}
        </select>
        <label className="relative ml-auto">
          <Search
            size={14}
            className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted"
            aria-hidden
          />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('shorts.search')}
            aria-label={t('shorts.search')}
            className="h-8 w-64 rounded-md border border-border bg-surface-2 pr-2 pl-8 text-sm"
          />
        </label>
      </div>

      {selected.length > 0 && (
        <Card className="sticky top-2 z-10 mb-4 flex items-center gap-3 px-4 py-2.5 text-sm shadow-lg">
          <span className="font-medium">{t('shorts.selected', { n: selected.length })}</span>
          <Button size="sm" onClick={() => act('approve')} disabled={bulk.isPending}>
            <Check size={14} aria-hidden /> {t('review.approve')}
          </Button>
          <Button
            size="sm"
            variant="danger"
            onClick={() => act('reject')}
            disabled={bulk.isPending}
          >
            <X size={14} aria-hidden /> {t('review.reject')}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setToDelete({ ids: selected })}>
            <Trash2 size={14} aria-hidden /> {t('shorts.delete.confirm')}
          </Button>
          <button
            className="ml-auto text-xs text-muted hover:text-fg"
            onClick={() => setSelected([])}
          >
            {t('shorts.clear')}
          </button>
          {bulk.data && bulk.data.skipped.length > 0 && (
            <span className="text-xs text-warn">
              {t('shorts.skipped', { n: bulk.data.skipped.length })}
            </span>
          )}
        </Card>
      )}

      {shorts.isLoading ? (
        <p className="text-sm text-muted">…</p>
      ) : items.length === 0 ? (
        <Card className="px-6 py-14 text-center text-sm text-muted">
          {q || qc || tab.status ? (
            t('shorts.noMatch')
          ) : (
            <>
              {t('shorts.empty')}{' '}
              <Link to="/create" className="text-accent hover:underline">
                {t('nav.create')}
              </Link>
            </>
          )}
        </Card>
      ) : (
        <>
          <p className="mb-3 text-xs text-muted">{t('shorts.count', { n: total })}</p>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
            {items.map((s) => (
              <ShortTile
                key={s.id}
                short={s}
                selected={selected.includes(s.id)}
                onToggle={() => toggle(s.id)}
                onDelete={() => setToDelete({ ids: [s.id], name: s.hook || s.title })}
              />
            ))}
          </div>
          {shorts.hasNextPage && (
            <div className="mt-6 text-center">
              <Button
                variant="secondary"
                onClick={() => void shorts.fetchNextPage()}
                disabled={shorts.isFetchingNextPage}
              >
                {shorts.isFetchingNextPage && (
                  <Loader2 size={14} className="animate-spin" aria-hidden />
                )}
                {t('shorts.more')}
              </Button>
            </div>
          )}
        </>
      )}
      <DeleteShortsDialog
        ids={toDelete.ids}
        name={toDelete.name}
        onClose={() => setToDelete({ ids: [] })}
        onDeleted={(gone) => setSelected((s) => s.filter((id) => !gone.includes(id)))}
      />
    </div>
  )
}
