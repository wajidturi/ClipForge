import { CheckCircle2, FlaskConical, History, Octagon, Trash2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ConfirmDialog } from '@/components/feedback'
import { toast } from '@/lib/toast'
import { JobRow } from '@/components/JobRow'
import { Button, Card, CardHeader } from '@/components/ui'
import type { Job } from '@/lib/api/client'
import {
  splitJobs,
  useClearJobHistory,
  useJobs,
  useStartSelftest,
  useStopAllJobs,
} from '@/lib/jobs'
import { useNow } from '@/lib/useNow'
import { PageHeader } from './Dashboard'

function Empty({ text }: { text: string }) {
  return (
    <div className="flex flex-col items-center gap-2 px-5 py-10 text-center text-sm text-muted">
      <CheckCircle2 size={22} aria-hidden />
      {text}
    </div>
  )
}

/** Running + queued jobs with Stop on each and Stop all. Also used on the dashboard. */
export function ActiveJobs({ jobs, footer }: { jobs: Job[]; footer?: ReactNode }) {
  const { t } = useTranslation()
  const stopAll = useStopAllJobs()
  const [confirm, setConfirm] = useState(false)
  const stoppable = jobs.filter((j) => !j.cancel_requested).length
  const now = useNow(
    2000,
    jobs.some((j) => j.status === 'queued'),
  )
  // A job still queued after 10 s with nothing running usually means no worker is up.
  const stuck =
    !jobs.some((j) => j.status === 'running') &&
    jobs.some((j) => j.status === 'queued' && now - Date.parse(j.created_at) > 10_000)

  const doStopAll = () =>
    stopAll.mutate(undefined, {
      onSuccess: (r) => {
        setConfirm(false)
        toast.ok(t('jobs.stoppedAll', { count: r.count }))
      },
      onError: () => toast.error(t('jobs.stopFailed')),
    })

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            {t('jobs.active')}
            {jobs.length > 0 && (
              <span className="rounded-full bg-accent/15 px-1.5 text-xs text-accent tabular-nums">
                {jobs.length}
              </span>
            )}
          </span>
        }
        action={
          stoppable > 0 && (
            <Button size="sm" variant="danger" onClick={() => setConfirm(true)}>
              <Octagon size={14} aria-hidden /> {t('jobs.stopAll')}
            </Button>
          )
        }
      />
      {stuck && (
        <p className="border-b border-border px-5 py-2.5 text-xs text-warn">
          {t('dashboard.noWorkers')}
        </p>
      )}
      {jobs.length === 0 ? (
        <Empty text={t('jobs.nothingRunning')} />
      ) : (
        <ul className="divide-y divide-border">
          {jobs.map((job) => (
            <JobRow key={job.id} job={job} />
          ))}
        </ul>
      )}
      {footer}
      <ConfirmDialog
        open={confirm}
        title={t('jobs.stopAllTitle', { count: stoppable })}
        confirmLabel={t('jobs.stopAll')}
        busy={stopAll.isPending}
        onConfirm={doStopAll}
        onClose={() => setConfirm(false)}
      >
        {t('jobs.stopAllBody')}
      </ConfirmDialog>
    </Card>
  )
}

function JobHistory({ jobs }: { jobs: Job[] }) {
  const { t } = useTranslation()
  const clear = useClearJobHistory()
  const [confirm, setConfirm] = useState(false)

  const doClear = () =>
    clear.mutate(undefined, {
      onSuccess: (r) => {
        setConfirm(false)
        toast.ok(t('jobs.cleared', { count: r.count }))
      },
      onError: () => toast.error(t('jobs.clearFailed')),
    })

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <History size={15} className="text-muted" aria-hidden /> {t('jobs.history')}
          </span>
        }
        action={
          jobs.length > 0 && (
            <Button size="sm" variant="ghost" onClick={() => setConfirm(true)}>
              <Trash2 size={14} aria-hidden /> {t('jobs.clearHistory')}
            </Button>
          )
        }
      />
      {jobs.length === 0 ? (
        <Empty text={t('jobs.historyEmpty')} />
      ) : (
        <ul className="divide-y divide-border">
          {jobs.map((job) => (
            <JobRow key={job.id} job={job} />
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={confirm}
        title={t('jobs.clearTitle')}
        confirmLabel={t('jobs.clearHistory')}
        busy={clear.isPending}
        onConfirm={doClear}
        onClose={() => setConfirm(false)}
      >
        {t('jobs.clearBody')}
      </ConfirmDialog>
    </Card>
  )
}

export function Jobs() {
  const { t } = useTranslation()
  const jobs = useJobs()
  const selftest = useStartSelftest()
  const { active, finished } = splitJobs(jobs.data?.items ?? [])
  return (
    <div className="mx-auto max-w-4xl px-8 py-8">
      <div className="flex items-start justify-between gap-4">
        <PageHeader title={t('jobs.title')} subtitle={t('jobs.subtitle')} />
        <Button
          size="sm"
          variant="ghost"
          onClick={() => selftest.mutate()}
          disabled={selftest.isPending}
          title={t('dashboard.selftestHelp')}
        >
          <FlaskConical size={14} aria-hidden /> {t('dashboard.selftest')}
        </Button>
      </div>
      {jobs.isError && <p className="mb-4 text-sm text-danger">{t('error.generic')}</p>}
      <div className="grid grid-cols-1 gap-6">
        <ActiveJobs jobs={active} />
        <JobHistory jobs={finished} />
      </div>
    </div>
  )
}
