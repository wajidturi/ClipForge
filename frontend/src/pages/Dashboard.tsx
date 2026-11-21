import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, FlaskConical } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { JobRow } from '@/components/JobRow'
import { Badge, Button, Card, CardHeader } from '@/components/ui'
import { api, unwrap } from '@/lib/api/client'
import { useJobs, useStartSelftest } from '@/lib/jobs'
import { useNow } from '@/lib/useNow'

export function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <header className="mb-6">
      <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
      {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
    </header>
  )
}

function Stat({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={warn ? 'mt-0.5 text-sm font-medium text-warn' : 'mt-0.5 text-sm font-medium'}>
        {value}
      </dd>
    </div>
  )
}

function SystemCard() {
  const { t } = useTranslation()
  const sys = useQuery({
    queryKey: ['system'],
    queryFn: async () => unwrap(await api.GET('/api/v1/system')),
    staleTime: 60_000,
  })
  const doc = useQuery({
    queryKey: ['doctor'],
    queryFn: async () => unwrap(await api.GET('/api/v1/system/doctor')),
    staleTime: 60_000,
  })
  const s = sys.data
  const failing = doc.data?.checks.filter((c) => !c.ok && c.required) ?? []

  return (
    <Card>
      <CardHeader
        title={t('dashboard.system')}
        action={
          doc.data &&
          (doc.data.ok ? (
            <Badge tone="ok">{t('system.allGood')}</Badge>
          ) : (
            <Badge tone="danger">{t('system.needsAttention')}</Badge>
          ))
        }
      />
      <div className="p-5">
        {sys.isError && <p className="text-sm text-danger">{t('error.generic')}</p>}
        {s && (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
            <Stat
              label={t('system.gpu')}
              value={s.gpus.length ? s.gpus.map((g) => g.name).join(', ') : t('system.noGpu')}
            />
            <Stat
              label={t('system.ram')}
              value={`${s.ram_gb} GB`}
              warn={s.light_mode_recommended}
            />
            <Stat label={t('system.disk')} value={`${s.disk_free_gb} GB`} />
            <Stat
              label={t('system.ffmpeg')}
              value={s.ffmpeg ?? t('system.missing')}
              warn={!s.ffmpeg}
            />
            <Stat label={t('system.database')} value={s.database} />
            <Stat label="Python" value={s.python} />
          </dl>
        )}
        {failing.length > 0 && (
          <ul className="mt-5 space-y-2">
            {failing.map((c) => (
              <li key={c.name} className="flex gap-2 rounded-lg bg-danger/10 p-3 text-sm">
                <AlertTriangle size={16} className="mt-0.5 shrink-0 text-danger" aria-hidden />
                <div>
                  <div className="font-medium">
                    {c.name}: {c.detail}
                  </div>
                  {c.fix && <div className="text-xs text-muted">{c.fix}</div>}
                </div>
              </li>
            ))}
          </ul>
        )}
        {s?.light_mode_recommended && (
          <p className="mt-4 text-xs text-warn">{t('system.lightMode')}</p>
        )}
      </div>
    </Card>
  )
}

function JobsCard() {
  const { t } = useTranslation()
  const jobs = useJobs()
  const start = useStartSelftest()
  const items = jobs.data?.items ?? []
  const anyQueued = items.some((j) => j.status === 'queued')
  const now = useNow(2000, anyQueued)
  // A job still queued after 5 s usually means no worker process is running.
  const stuck = items.some((j) => j.status === 'queued' && now - Date.parse(j.created_at) > 5_000)

  return (
    <Card>
      <CardHeader
        title={t('dashboard.jobs')}
        action={
          <Button size="sm" onClick={() => start.mutate()} disabled={start.isPending}>
            <FlaskConical size={14} aria-hidden /> {t('dashboard.selftest')}
          </Button>
        }
      />
      {stuck && (
        <p className="border-b border-border px-5 py-2.5 text-xs text-warn">
          {t('dashboard.noWorkers')}
        </p>
      )}
      {items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 px-5 py-10 text-center text-sm text-muted">
          <CheckCircle2 size={22} aria-hidden />
          {jobs.isLoading ? '…' : t('dashboard.jobsEmpty')}
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((job) => (
            <JobRow key={job.id} job={job} />
          ))}
        </ul>
      )}
    </Card>
  )
}

export function Dashboard() {
  const { t } = useTranslation()
  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <PageHeader title={t('dashboard.title')} subtitle={t('dashboard.subtitle')} />
      <div className="grid gap-6">
        <SystemCard />
        <JobsCard />
      </div>
    </div>
  )
}
