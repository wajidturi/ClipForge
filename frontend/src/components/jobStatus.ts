import type { JobStatus } from '@/lib/api/client'
import type { Tone } from './ui'

export const STATUS_TONE: Record<JobStatus, Tone> = {
  queued: 'neutral',
  running: 'info',
  succeeded: 'ok',
  failed: 'danger',
  cancelled: 'warn',
}
