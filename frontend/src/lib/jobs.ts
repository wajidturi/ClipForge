import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { api, unwrap, type Job, type JobPage } from './api/client'
import { mergeItem } from './merge'

export const jobKeys = {
  all: ['jobs'] as const,
  list: () => [...jobKeys.all, 'list'] as const,
  detail: (id: string) => [...jobKeys.all, 'detail', id] as const,
}

export function useJobs() {
  return useQuery({
    queryKey: jobKeys.list(),
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/jobs', { params: { query: { limit: 50 } } })),
  })
}

export const mergeJob = (page: JobPage | undefined, job: Job): JobPage => mergeItem(page, job)

/** One job, kept live by WebSocket events (see applyJobEvent). */
export function useJob(id: string | null | undefined) {
  return useQuery({
    queryKey: jobKeys.detail(id ?? 'none'),
    enabled: Boolean(id),
    staleTime: Infinity,
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/jobs/{job_id}', { params: { path: { job_id: id! } } })),
  })
}

export function applyJobEvent(qc: QueryClient, job: Job) {
  qc.setQueryData<JobPage>(jobKeys.list(), (page) => mergeJob(page, job))
  qc.setQueryData<Job>(jobKeys.detail(job.id), (old) =>
    old && old.updated_at > job.updated_at ? old : job,
  )
}

function useJobMutation(fn: () => Promise<Job>) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: (job) => applyJobEvent(qc, job) })
}

export function useStartSelftest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST('/api/v1/jobs', {
          body: {
            type: 'system.selftest',
            label: 'Self-test',
            payload: { steps: 20, delay: 0.25 },
          },
        }),
      ),
    onSuccess: (job) => applyJobEvent(qc, job),
  })
}

export function useCancelJob(id: string) {
  return useJobMutation(async () =>
    unwrap(await api.POST('/api/v1/jobs/{job_id}/cancel', { params: { path: { job_id: id } } })),
  )
}

export function useRetryJob(id: string) {
  return useJobMutation(async () =>
    unwrap(await api.POST('/api/v1/jobs/{job_id}/retry', { params: { path: { job_id: id } } })),
  )
}
