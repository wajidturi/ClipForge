import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import {
  ApiError,
  api,
  unwrap,
  type Run,
  type RunCreate,
  type RunDetail,
  type RenderRequest,
  type ShortPatch,
} from './api/client'

export const runKeys = {
  all: ['runs'] as const,
  list: () => [...runKeys.all, 'list'] as const,
  detail: (id: string) => [...runKeys.all, 'detail', id] as const,
  ai: () => ['ai', 'status'] as const,
}

export function useRuns() {
  return useQuery({
    queryKey: runKeys.list(),
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/runs', { params: { query: { limit: 20 } } })),
  })
}

export function useRun(id: string) {
  return useQuery({
    queryKey: runKeys.detail(id),
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/runs/{run_id}', { params: { path: { run_id: id } } })),
  })
}

export function useAIStatus() {
  return useQuery({
    queryKey: runKeys.ai(),
    staleTime: 30_000,
    queryFn: async () => unwrap(await api.GET('/api/v1/ai/status')),
  })
}

/** WebSocket `run.updated`: refresh the list and that run's detail (picks appear at the end). */
export function applyRunEvent(qc: QueryClient, run: Run) {
  void qc.invalidateQueries({ queryKey: runKeys.list() })
  qc.setQueryData<RunDetail>(runKeys.detail(run.id), (old) => (old ? { ...old, ...run } : old))
  if (run.status === 'succeeded' || run.status === 'failed')
    void qc.invalidateQueries({ queryKey: runKeys.detail(run.id) })
}

export function useCreateRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: RunCreate) => unwrap(await api.POST('/api/v1/runs', { body })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: runKeys.list() }),
  })
}

export function useEditShort(runId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, patch }: { id: string; patch: ShortPatch }) =>
      unwrap(
        await api.PATCH('/api/v1/shorts/{short_id}', {
          params: { path: { short_id: id } },
          body: patch,
        }),
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: runKeys.detail(runId) }),
  })
}

export function useDropShort(runId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const r = await api.DELETE('/api/v1/shorts/{short_id}', {
        params: { path: { short_id: id } },
      })
      if (!r.response.ok)
        throw new ApiError(`Drop failed (${r.response.status})`, r.response.status)
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: runKeys.detail(runId) }),
  })
}

export const previewUrl = (shortId: string, start: number, end: number) =>
  `/api/v1/shorts/${shortId}/preview.jpg?r=${start.toFixed(2)}-${end.toFixed(2)}`

// ------------------------------------------------------------------ rendering
export function useRenderOptions() {
  return useQuery({
    queryKey: ['render', 'options'],
    staleTime: Infinity,
    queryFn: async () => unwrap(await api.GET('/api/v1/render/options')),
  })
}

export function useRenderRun(runId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: RenderRequest) =>
      unwrap(
        await api.POST('/api/v1/runs/{run_id}/render', {
          params: { path: { run_id: runId } },
          body,
        }),
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: runKeys.detail(runId) }),
  })
}

export function useRenderShort(runId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, body }: { id: string; body: RenderRequest }) =>
      unwrap(
        await api.POST('/api/v1/shorts/{short_id}/render', {
          params: { path: { short_id: id } },
          body,
        }),
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: runKeys.detail(runId) }),
  })
}

/** WebSocket `short.updated`: refresh the run that owns it (status, new version). */
export function applyShortEvent(qc: QueryClient, ev: { run_id: string | null }) {
  if (ev.run_id) void qc.invalidateQueries({ queryKey: runKeys.detail(ev.run_id) })
}
