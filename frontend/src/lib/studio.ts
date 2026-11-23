import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import {
  ApiError,
  api,
  unwrap,
  type ImageInfo,
  type Scene,
  type TemplateChoice,
} from './api/client'
import { shortKeys } from './shorts'

export const studioKeys = {
  studio: (id: string) => [...shortKeys.all, 'studio', id] as const,
  images: () => ['images'] as const,
}

export function useStudio(id: string) {
  return useQuery({
    queryKey: studioKeys.studio(id),
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/shorts/{short_id}/studio', { params: { path: { short_id: id } } }),
      ),
  })
}

export function useSwitchTemplate(id: string) {
  return useMutation({
    mutationFn: async (v: { template: TemplateChoice; scene: Scene }) =>
      unwrap(
        await api.POST('/api/v1/shorts/{short_id}/scene/template', {
          params: { path: { short_id: id } },
          body: v,
        }),
      ) as Scene,
  })
}

export function useImages() {
  return useQuery({
    queryKey: studioKeys.images(),
    queryFn: async () => unwrap(await api.GET('/api/v1/images')),
  })
}

export function useUploadImage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (file: File): Promise<ImageInfo> => {
      const form = new FormData()
      form.append('file', file)
      const r = await globalThis.fetch('/api/v1/images', { method: 'POST', body: form })
      const data = (await r.json().catch(() => ({}))) as ImageInfo & { detail?: string }
      if (!r.ok) throw new ApiError(data.detail ?? `Upload failed (${r.status})`, r.status)
      return data
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: studioKeys.images() }),
  })
}

export function useDeleteImage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const r = await api.DELETE('/api/v1/images/{image_id}', {
        params: { path: { image_id: id } },
      })
      if (!r.response.ok)
        throw new ApiError(`Delete failed (${r.response.status})`, r.response.status)
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: studioKeys.images() }),
  })
}

/**
 * Undo/redo for the scene. `set(next)` records a step; `set(next, true)` updates
 * without recording (used while dragging) and `commit()` records the drag as one
 * step from where it started.
 */
export function useHistory<T>(initial: T, limit = 100) {
  const [state, setState] = useState({
    past: [] as T[],
    present: initial,
    future: [] as T[],
    base: null as T | null,
  })
  const set = useCallback(
    (next: T | ((cur: T) => T), transient = false) =>
      setState((s) => {
        const value = typeof next === 'function' ? (next as (c: T) => T)(s.present) : next
        if (transient) return { ...s, present: value, base: s.base ?? s.present }
        return {
          past: [...s.past, s.present].slice(-limit),
          present: value,
          future: [],
          base: null,
        }
      }),
    [limit],
  )
  const commit = useCallback(
    () =>
      setState((s) =>
        s.base === null
          ? s
          : { past: [...s.past, s.base].slice(-limit), present: s.present, future: [], base: null },
      ),
    [limit],
  )
  const undo = useCallback(
    () =>
      setState((s) =>
        s.past.length
          ? {
              past: s.past.slice(0, -1),
              present: s.past[s.past.length - 1]!,
              future: [s.present, ...s.future],
              base: null,
            }
          : s,
      ),
    [],
  )
  const redo = useCallback(
    () =>
      setState((s) =>
        s.future.length
          ? {
              past: [...s.past, s.present],
              present: s.future[0]!,
              future: s.future.slice(1),
              base: null,
            }
          : s,
      ),
    [],
  )
  return {
    value: state.present,
    set,
    commit,
    undo,
    redo,
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
  }
}
