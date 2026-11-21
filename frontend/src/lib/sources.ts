import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import {
  ApiError,
  api,
  unwrap,
  type AnalyzeOptions,
  type Source,
  type SourceCreated,
  type SourceDetail,
  type SourcePage,
} from './api/client'
import { mergeItem, removeItem } from './merge'

export const sourceKeys = {
  all: ['sources'] as const,
  list: () => [...sourceKeys.all, 'list'] as const,
  detail: (id: string) => [...sourceKeys.all, 'detail', id] as const,
  // nested under detail: a source event invalidates its transcript and timeline too
  transcript: (id: string) => [...sourceKeys.detail(id), 'transcript'] as const,
  timeline: (id: string, bins: number) => [...sourceKeys.detail(id), 'timeline', bins] as const,
  platforms: () => [...sourceKeys.all, 'platforms'] as const,
}

export function useTranscript(id: string, enabled: boolean) {
  return useQuery({
    queryKey: sourceKeys.transcript(id),
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/sources/{source_id}/transcript', {
          params: { path: { source_id: id } },
        }),
      ),
  })
}

export function useTimeline(id: string, bins: number, enabled: boolean) {
  return useQuery({
    queryKey: sourceKeys.timeline(id, bins),
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/sources/{source_id}/timeline', {
          params: { path: { source_id: id }, query: { bins } },
        }),
      ),
  })
}

export function useAnalyze(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: AnalyzeOptions) =>
      unwrap(
        await api.POST('/api/v1/sources/{source_id}/analyze', {
          params: { path: { source_id: id } },
          body,
        }),
      ),
    onSuccess: (r) => applySourceEvent(qc, r.source),
  })
}

export function useSources() {
  return useQuery({
    queryKey: sourceKeys.list(),
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/sources', { params: { query: { limit: 100 } } })),
  })
}

export function useSource(id: string | null) {
  return useQuery({
    queryKey: sourceKeys.detail(id ?? 'none'),
    enabled: Boolean(id),
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/sources/{source_id}', { params: { path: { source_id: id! } } }),
      ),
  })
}

export function usePlatforms() {
  return useQuery({
    queryKey: sourceKeys.platforms(),
    staleTime: Infinity,
    queryFn: async () => unwrap(await api.GET('/api/v1/sources/platforms')),
  })
}

export function applySourceEvent(qc: QueryClient, src: Source) {
  qc.setQueryData<SourcePage>(sourceKeys.list(), (page) => mergeItem(page, src))
  // the detail view also shows assets, which only a refetch provides
  void qc.invalidateQueries({ queryKey: sourceKeys.detail(src.id) })
}

export function applySourceDeleted(qc: QueryClient, id: string) {
  qc.setQueryData<SourcePage>(sourceKeys.list(), (page) => removeItem(page, id))
  qc.removeQueries({ queryKey: sourceKeys.detail(id) })
}

export function useAddSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: { url: string; start?: string; end?: string }) =>
      unwrap(await api.POST('/api/v1/sources', { body })),
    onSuccess: (r) => applySourceEvent(qc, r.source),
  })
}

/** Upload with a progress callback (fetch cannot report upload progress; XHR can). */
export function uploadSource(
  file: File,
  window: { start?: string; end?: string },
  onProgress: (pct: number) => void,
  signal?: AbortSignal,
): Promise<SourceCreated> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const form = new FormData()
    form.append('file', file)
    if (window.start) form.append('start', window.start)
    if (window.end) form.append('end', window.end)
    xhr.open('POST', '/api/v1/sources/upload')
    xhr.responseType = 'json'
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress((e.loaded / e.total) * 100)
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as SourceCreated)
      else {
        const detail = (xhr.response as { detail?: unknown } | null)?.detail
        reject(
          new ApiError(
            typeof detail === 'string' ? detail : `Upload failed (${xhr.status})`,
            xhr.status,
          ),
        )
      }
    }
    xhr.onerror = () => reject(new ApiError('Upload failed: network error', 0))
    signal?.addEventListener('abort', () => xhr.abort())
    xhr.onabort = () => reject(new ApiError('Upload cancelled', 0))
    xhr.send(form)
  })
}

export function useUploadSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (args: {
      file: File
      start?: string
      end?: string
      onProgress: (pct: number) => void
    }) => uploadSource(args.file, { start: args.start, end: args.end }, args.onProgress),
    onSuccess: (r) => applySourceEvent(qc, r.source),
  })
}

export function useRetrySource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST('/api/v1/sources/{source_id}/retry', {
          params: { path: { source_id: id } },
        }),
      ),
    onSuccess: (r) => applySourceEvent(qc, r.source),
  })
}

export function useDeleteSource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const r = await api.DELETE('/api/v1/sources/{source_id}', {
        params: { path: { source_id: id } },
      })
      if (!r.response.ok)
        throw new ApiError(`Delete failed (${r.response.status})`, r.response.status)
      return id
    },
    onSuccess: (id) => applySourceDeleted(qc, id),
  })
}

export const IN_PROGRESS: readonly Source['status'][] = ['new', 'downloading', 'analyzing']

export type { SourceDetail }
