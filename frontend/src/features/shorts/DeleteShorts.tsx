import { useTranslation } from 'react-i18next'
import { ConfirmDialog } from '@/components/feedback'
import { toast } from '@/lib/toast'
import { useDeleteShorts } from '@/lib/shorts'

/** Confirmation + permanent delete of one or more Shorts, with a result message. */
export function DeleteShortsDialog({
  ids,
  name,
  onClose,
  onDeleted,
}: {
  ids: string[] // empty = closed
  name?: string | null // shown when deleting one Short
  onClose: () => void
  onDeleted?: (deleted: string[]) => void
}) {
  const { t } = useTranslation()
  const del = useDeleteShorts()
  const n = ids.length
  const confirm = () =>
    del.mutate(ids, {
      onSuccess: (r) => {
        toast.ok(t('shorts.delete.done', { count: r.deleted.length }))
        onDeleted?.(r.deleted)
        onClose()
      },
      onError: () => toast.error(t('shorts.delete.failed')),
    })
  return (
    <ConfirmDialog
      open={n > 0}
      title={
        n === 1 && name
          ? t('shorts.delete.titleOne', { name })
          : t('shorts.delete.title', { count: n })
      }
      confirmLabel={t('shorts.delete.confirm')}
      busy={del.isPending}
      onConfirm={confirm}
      onClose={onClose}
    >
      {t('shorts.delete.body', { count: n })}
    </ConfirmDialog>
  )
}
