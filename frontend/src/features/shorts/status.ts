import type { Tone } from '@/components/ui'
import type { ShortStatus } from '@/lib/api/client'

export const STATUS_TONE: Record<ShortStatus, Tone> = {
  picked: 'neutral',
  rendering: 'info',
  review: 'accent',
  approved: 'ok',
  rejected: 'danger',
  scheduled: 'info',
  published: 'ok',
  failed: 'danger',
  dropped: 'neutral',
}
export const QC_TONE: Record<string, Tone> = { pass: 'ok', warn: 'warn', fail: 'danger' }
