import { RotateCcw, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { FINAL_STATUSES, type Job } from '@/lib/api/client'
import { useCancelJob, useRetryJob } from '@/lib/jobs'
import { useNow } from '@/lib/useNow'
import { formatDuration } from '@/lib/utils'
import { STATUS_TONE } from './jobStatus'
import { Badge, Button, Progress } from './ui'

export function JobRow({ job }: { job: Job }) {
  const { t } = useTranslation()
  const cancel = useCancelJob(job.id)
  const retry = useRetryJob(job.id)
  const done = FINAL_STATUSES.includes(job.status)
  const now = useNow(1000, job.status === 'running')
  const elapsed =
    job.started_at &&
    (job.finished_at ? Date.parse(job.finished_at) : now) - Date.parse(job.started_at)

  return (
    <li className="flex flex-col gap-2 px-5 py-3.5" data-testid="job-row">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium">{job.label ?? job.type}</span>
            <Badge tone={STATUS_TONE[job.status]}>{t(`job.status.${job.status}`)}</Badge>
            {job.attempts > 1 && (
              <span className="text-xs text-muted">
                {t('job.attempt', { n: job.attempts, max: job.max_attempts })}
              </span>
            )}
          </div>
          <div className="mt-0.5 truncate text-xs text-muted">
            {job.cancel_requested && !done ? t('job.cancelling') : (job.step ?? job.type)}
            {elapsed ? ` · ${formatDuration(elapsed)}` : ''}
          </div>
        </div>
        {!done && !job.cancel_requested && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => cancel.mutate()}
            disabled={cancel.isPending}
          >
            <X size={14} aria-hidden /> {t('job.cancel')}
          </Button>
        )}
        {(job.status === 'failed' || job.status === 'cancelled') && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => retry.mutate()}
            disabled={retry.isPending}
          >
            <RotateCcw size={14} aria-hidden /> {t('job.retry')}
          </Button>
        )}
      </div>
      {!done && (
        <Progress value={job.progress} tone={job.status === 'running' ? 'accent' : 'neutral'} />
      )}
      {job.status === 'failed' && job.error && (
        <pre className="max-h-24 overflow-auto rounded-md bg-surface-2 p-2 text-xs whitespace-pre-wrap text-danger">
          {job.error.split('\n')[0]}
        </pre>
      )}
    </li>
  )
}
