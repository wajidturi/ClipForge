import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, type SettingField, type SettingsPatch } from './api/client'
import { runKeys } from './runs'

export const settingsKeys = { all: ['settings'] as const }

export function useSettings() {
  return useQuery({
    queryKey: settingsKeys.all,
    staleTime: 30_000,
    queryFn: async () => unwrap(await api.GET('/api/v1/settings')),
    select: (d) => d.fields,
  })
}

export function useSaveSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: SettingsPatch) =>
      unwrap(await api.PATCH('/api/v1/settings', { body })),
    onSuccess: (d) => {
      qc.setQueryData(settingsKeys.all, d)
      void qc.invalidateQueries({ queryKey: runKeys.ai() })
    },
  })
}

/** Field value by key (typed loosely: the form decides how to edit it). */
export function settingValue<T = unknown>(fields: SettingField[] | undefined, key: string) {
  return fields?.find((f) => f.key === key)?.value as T | undefined
}
