/** Feedback primitives: toasts for results of actions, and a confirm dialog. */
import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react'
import { useEffect, useId, useRef, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useToasts } from '@/lib/toast'
import { cn } from '@/lib/utils'
import { Button } from './ui'

const ICON = { ok: CheckCircle2, danger: AlertTriangle, info: Info }
const TONE = { ok: 'text-ok', danger: 'text-danger', info: 'text-info' }

export function Toaster() {
  const { t } = useTranslation()
  const { items, drop } = useToasts()
  return (
    <div
      className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-80 flex-col gap-2"
      role="status"
      aria-live="polite"
    >
      {items.map((x) => {
        const Icon = ICON[x.tone]
        return (
          <div
            key={x.id}
            className="pointer-events-auto flex items-start gap-2.5 rounded-xl border border-border bg-surface px-3.5 py-3 text-sm shadow-lg"
          >
            <Icon size={16} className={cn('mt-0.5 shrink-0', TONE[x.tone])} aria-hidden />
            <p className="min-w-0 flex-1">{x.text}</p>
            <button
              onClick={() => drop(x.id)}
              className="text-muted hover:text-fg"
              aria-label={t('common.dismiss')}
            >
              <X size={14} />
            </button>
          </div>
        )
      })}
    </div>
  )
}

/** Modal confirmation for actions that cannot be undone. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  busy,
  onConfirm,
  onClose,
}: {
  open: boolean
  title: string
  children?: ReactNode
  confirmLabel: string
  busy?: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const titleId = useId()
  const cancelRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!open) return
    cancelRef.current?.focus() // the safe choice is the default
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !busy && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, busy, onClose])
  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/50 p-4 backdrop-blur-[2px]"
      onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-md rounded-2xl border border-border bg-surface p-5 shadow-2xl"
      >
        <div className="flex gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-danger/12 text-danger">
            <AlertTriangle size={18} aria-hidden />
          </div>
          <div className="min-w-0">
            <h2 id={titleId} className="text-base font-semibold">
              {title}
            </h2>
            {children && <div className="mt-1.5 text-sm text-muted">{children}</div>}
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button ref={cancelRef} variant="secondary" onClick={onClose} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button
            className="bg-danger text-white hover:opacity-90"
            variant="primary"
            onClick={onConfirm}
            disabled={busy}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
