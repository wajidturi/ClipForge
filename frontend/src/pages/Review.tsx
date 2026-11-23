import { Check, ChevronLeft, ChevronRight, Download, PartyPopper, Pencil, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import { Button, Card } from '@/components/ui'
import { QcBadge } from '@/features/shorts/ShortTile'
import { mediaUrl } from '@/lib/api/client'
import { exportUrl, useReview, useShorts } from '@/lib/shorts'
import { formatClock } from '@/lib/utils'
import { PageHeader } from './Dashboard'

const FILTER = { status: ['review' as const] }

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="ml-1.5 rounded border border-current/30 px-1 font-mono text-[10px] opacity-70">
      {children}
    </kbd>
  )
}

/** One Short at a time: watch, then approve (A) or reject (R); J/K move through the queue. */
export function Review() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queue = useShorts(FILTER, 50)
  const items = queue.data?.pages.flatMap((p) => p.items) ?? []
  const total = queue.data?.pages[0]?.total ?? 0
  const [idx, setIdx] = useState(0)
  const at = Math.min(idx, Math.max(0, items.length - 1)) // the list shrinks as you review
  const cur = items[at]
  const review = useReview()
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const reasonRef = useRef<HTMLInputElement>(null)

  const act = useCallback(
    (action: 'approve' | 'reject', why?: string) => {
      if (!cur || review.isPending) return
      review.mutate(
        { id: cur.id, action, reason: why || null },
        {
          onSuccess: () => {
            setRejecting(false)
            setReason('')
          },
        },
      )
    },
    [cur, review],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable))
        return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const k = e.key.toLowerCase()
      if (k === 'a') act('approve')
      else if (k === 'r') {
        e.preventDefault()
        setRejecting(true)
        setTimeout(() => reasonRef.current?.focus(), 0)
      } else if (k === 'j') setIdx(Math.min(at + 1, items.length - 1))
      else if (k === 'k') setIdx(Math.max(at - 1, 0))
      else if (k === 'e' && cur) navigate(`/shorts/${cur.id}`)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [act, at, cur, items.length, navigate])

  const submitReject = (e: FormEvent) => {
    e.preventDefault()
    act('reject', reason.trim())
  }

  if (queue.isLoading) return <p className="px-8 py-8 text-sm text-muted">…</p>
  if (!cur)
    return (
      <div className="mx-auto max-w-5xl px-8 py-8">
        <PageHeader title={t('review.title')} subtitle={t('review.subtitle')} />
        <Card className="flex flex-col items-center gap-3 px-6 py-16 text-center text-sm text-muted">
          <PartyPopper size={28} aria-hidden />
          <p>{t('review.empty')}</p>
          <Link to="/shorts?tab=approved" className="text-accent hover:underline">
            {t('review.seeApproved')}
          </Link>
        </Card>
      </div>
    )

  const v = cur.active
  const part = cur.parts?.[0]
  const pos = at + 1

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <PageHeader title={t('review.title')} subtitle={t('review.subtitle')} />
      <div className="grid gap-6 md:grid-cols-[minmax(0,22rem)_1fr]">
        <div className="mx-auto w-full max-w-[22rem]">
          {v?.mp4_asset_id ? (
            <video
              key={v.id}
              controls
              autoPlay
              playsInline
              poster={v.cover_asset_id ? mediaUrl(v.cover_asset_id) : undefined}
              src={mediaUrl(v.mp4_asset_id)}
              className="aspect-[9/16] w-full rounded-xl bg-black object-contain"
              aria-label={t('render.player')}
            />
          ) : (
            <div className="flex aspect-[9/16] items-center justify-center rounded-xl bg-surface-2 text-sm text-muted">
              {t('review.noVideo')}
            </div>
          )}
        </div>
        <div className="min-w-0 space-y-5">
          <div className="flex items-center gap-2 text-xs text-muted">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setIdx(Math.max(at - 1, 0))}
              disabled={pos <= 1}
              aria-label={t('review.prev')}
            >
              <ChevronLeft size={14} aria-hidden />
              <Kbd>K</Kbd>
            </Button>
            <span className="tabular-nums">{t('review.position', { pos, total })}</span>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setIdx(Math.min(at + 1, items.length - 1))}
              disabled={pos >= items.length}
              aria-label={t('review.next')}
            >
              <Kbd>J</Kbd>
              <ChevronRight size={14} aria-hidden />
            </Button>
          </div>

          <div>
            <h2 className="text-lg font-semibold tracking-wide">{cur.hook}</h2>
            <p className="mt-1 text-sm">{cur.title}</p>
            <p className="mt-1 text-xs text-muted">{cur.hashtags.join(' ')}</p>
          </div>

          <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-3">
            <div>
              <dt className="text-muted">{t('review.source')}</dt>
              <dd className="truncate">{cur.source_title ?? '–'}</dd>
            </div>
            <div>
              <dt className="text-muted">{t('review.range')}</dt>
              <dd className="tabular-nums">
                {part ? `${formatClock(part.start_s)}–${formatClock(part.end_s)}` : '–'}
              </dd>
            </div>
            <div>
              <dt className="text-muted">{t('review.length')}</dt>
              <dd>{v?.duration_s ? `${Math.round(v.duration_s)}s` : '–'}</dd>
            </div>
          </dl>

          <div className="space-y-1.5">
            <QcBadge verdict={v?.qc_verdict} />
            {(v?.qc_reasons?.length ?? 0) > 0 && (
              <ul className="text-xs text-warn">
                {v!.qc_reasons!.map((r, i) => (
                  <li key={i}>• {r}</li>
                ))}
              </ul>
            )}
            {cur.ai_reason && <p className="text-xs italic text-muted">{cur.ai_reason}</p>}
          </div>

          {rejecting ? (
            <form onSubmit={submitReject} className="flex flex-wrap gap-2">
              <input
                ref={reasonRef}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                onKeyDown={(e) => e.key === 'Escape' && setRejecting(false)}
                placeholder={t('review.reasonPh')}
                aria-label={t('review.reason')}
                maxLength={500}
                className="h-9 min-w-60 flex-1 rounded-lg border border-border bg-surface-2 px-3 text-sm"
              />
              <Button type="submit" variant="danger" disabled={review.isPending}>
                <X size={14} aria-hidden /> {t('review.reject')}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setRejecting(false)}>
                {t('runs.cancel')}
              </Button>
            </form>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => act('approve')} disabled={review.isPending}>
                <Check size={15} aria-hidden /> {t('review.approve')}
                <Kbd>A</Kbd>
              </Button>
              <Button
                variant="danger"
                onClick={() => setRejecting(true)}
                disabled={review.isPending}
              >
                <X size={15} aria-hidden /> {t('review.reject')}
                <Kbd>R</Kbd>
              </Button>
              <Link
                to={`/shorts/${cur.id}`}
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-surface-2 px-4 text-sm font-medium hover:bg-border/60"
              >
                <Pencil size={14} aria-hidden /> {t('review.edit')}
                <Kbd>E</Kbd>
              </Link>
              <a
                href={exportUrl(cur.id)}
                className="inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm text-muted hover:bg-surface-2 hover:text-fg"
              >
                <Download size={14} aria-hidden /> ZIP
              </a>
            </div>
          )}
          {review.error && <p className="text-sm text-danger">{review.error.message}</p>}
          <p className="text-xs text-muted">{t('review.keys')}</p>
        </div>
      </div>
    </div>
  )
}
