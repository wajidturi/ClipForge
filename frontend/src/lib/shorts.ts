/**
 * Shorts library, review queue and studio data. Every mutation invalidates the
 * lists, the Short itself, its run page and the dashboard counts; WebSocket
 * `short.updated` events do the same, so all open screens stay in sync.
 */
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import {
  api,
  unwrap,
  type RenderRequest,
  type ReviewAction,
  type ShortPatch,
  type ShortStatus,
} from './api/client'
import { runKeys } from './runs'

export type LibraryFilter = {
  status?: ShortStatus[]
  qc?: 'pass' | 'warn' | 'fail'
  q?: string
  run_id?: string
  source_id?: string
}

export const shortKeys = {
  all: ['shorts'] as const,
  lists: () => [...shortKeys.all, 'list'] as const,
  list: (f: LibraryFilter) => [...shortKeys.lists(), f] as const,
  detail: (id: string) => [...shortKeys.all, 'detail', id] as const,
  words: (id: string) => [...shortKeys.all, 'words', id] as const,
  edits: (id: string) => [...shortKeys.all, 'edits', id] as const,
  stats: () => ['stats'] as const,
}

export function useShorts(filter: LibraryFilter, pageSize = 24) {
  return useInfiniteQuery({
    queryKey: shortKeys.list(filter),
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET('/api/v1/shorts', {
          params: {
            query: {
              ...filter,
              q: filter.q?.trim() || undefined,
              cursor: pageParam,
              limit: pageSize,
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    placeholderData: keepPreviousData, // keep the grid while a new filter loads
  })
}

export function useShort(id: string) {
  return useQuery({
    queryKey: shortKeys.detail(id),
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/shorts/{short_id}', { params: { path: { short_id: id } } })),
  })
}

export function useStats() {
  return useQuery({
    queryKey: shortKeys.stats(),
    queryFn: async () => unwrap(await api.GET('/api/v1/stats')),
  })
}

export function useShortWords(id: string, enabled = true) {
  return useQuery({
    queryKey: shortKeys.words(id),
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/shorts/{short_id}/words', { params: { path: { short_id: id } } }),
      ),
  })
}

export function useEdits(id: string) {
  return useQuery({
    queryKey: shortKeys.edits(id),
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/shorts/{short_id}/edits', { params: { path: { short_id: id } } }),
      ),
  })
}

/** Refresh everything that shows this Short. */
export function refreshShort(qc: QueryClient, id: string | null, runId?: string | null) {
  void qc.invalidateQueries({ queryKey: shortKeys.lists() })
  void qc.invalidateQueries({ queryKey: shortKeys.stats() })
  if (id) {
    void qc.invalidateQueries({ queryKey: shortKeys.detail(id) })
    void qc.invalidateQueries({ queryKey: shortKeys.words(id) })
    void qc.invalidateQueries({ queryKey: shortKeys.edits(id) })
  }
  if (runId) void qc.invalidateQueries({ queryKey: runKeys.detail(runId) })
}

export function useReview() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (v: { id: string; action: ReviewAction; reason?: string | null }) =>
      unwrap(
        await api.POST('/api/v1/shorts/{short_id}/review', {
          params: { path: { short_id: v.id } },
          body: { action: v.action, reason: v.reason ?? null },
        }),
      ),
    onSuccess: (s) => refreshShort(qc, s.id, s.run_id),
  })
}

export function useBulkReview() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (v: { ids: string[]; action: ReviewAction; reason?: string | null }) =>
      unwrap(
        await api.POST('/api/v1/shorts/review', {
          body: { short_ids: v.ids, action: v.action, reason: v.reason ?? null },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: shortKeys.all })
      void qc.invalidateQueries({ queryKey: shortKeys.stats() })
      void qc.invalidateQueries({ queryKey: runKeys.all })
    },
  })
}

export function usePatchShort(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (patch: ShortPatch) =>
      unwrap(
        await api.PATCH('/api/v1/shorts/{short_id}', {
          params: { path: { short_id: id } },
          body: patch,
        }),
      ),
    onSuccess: (s) => refreshShort(qc, s.id, s.run_id),
  })
}

export function useRenderOne(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: RenderRequest) =>
      unwrap(
        await api.POST('/api/v1/shorts/{short_id}/render', {
          params: { path: { short_id: id } },
          body,
        }),
      ),
    onSuccess: () => refreshShort(qc, id),
  })
}

export function usePlanEdit(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (instruction: string) =>
      unwrap(
        await api.POST('/api/v1/shorts/{short_id}/ai-edit', {
          params: { path: { short_id: id } },
          body: { instruction },
        }),
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: shortKeys.edits(id) }),
  })
}

export function useApplyEdit(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (editId: string) =>
      unwrap(
        await api.POST('/api/v1/edits/{edit_id}/apply', {
          params: { path: { edit_id: editId } },
        }),
      ),
    onSuccess: (r) => refreshShort(qc, id, r.short.run_id),
  })
}

export const exportUrl = (shortId: string) => `/api/v1/shorts/${shortId}/export.zip`
export const runExportUrl = (runId: string, only: 'approved' | 'rendered' = 'approved') =>
  `/api/v1/runs/${runId}/export.zip?only=${only}`

/** WebSocket `short.updated`. */
export function applyShortUpdated(qc: QueryClient, ev: { id: string; run_id: string | null }) {
  refreshShort(qc, ev.id, ev.run_id)
}
