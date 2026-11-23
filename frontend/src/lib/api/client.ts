/**
 * Typed API client. `schema.d.ts` is generated from the backend's OpenAPI document
 * (`npm run gen:api`), so a backend change that breaks the contract breaks `tsc`.
 */
import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export type Job = components['schemas']['JobOut']
export type JobStatus = Job['status']
export type SystemInfo = components['schemas']['SystemOut']
export type Doctor = components['schemas']['DoctorOut']
export type JobPage = components['schemas']['JobPage']
export type Source = components['schemas']['SourceOut']
export type SourceDetail = components['schemas']['SourceDetail']
export type SourcePage = components['schemas']['SourcePage']
export type SourceCreated = components['schemas']['SourceCreated']
export type SourceStatus = Source['status']
export type PlatformInfo = components['schemas']['PlatformOut']
export type Transcript = components['schemas']['TranscriptOut']
export type TranscriptSegment = components['schemas']['SegmentOut']
export type Timeline = components['schemas']['TimelineOut']
export type TimelineMarker = components['schemas']['Marker']
export type AnalyzeOptions = components['schemas']['AnalyzeRequest']
export type Run = components['schemas']['RunOut']
export type RunDetail = components['schemas']['RunDetail']
export type RunCreate = components['schemas']['RunCreate']
export type ShortPick = components['schemas']['ShortOut']
export type ShortPatch = components['schemas']['ShortPatch']
export type AIStatus = components['schemas']['AIStatusOut']
export type PickMode = RunCreate['pick_mode']
export type ActiveVersion = components['schemas']['ActiveVersion']
export type RenderOptions = components['schemas']['RenderOptions']
export type RenderRequest = components['schemas']['RenderRequest']
export type Aspect = NonNullable<RenderRequest['aspects']>[number]
export type Layout = NonNullable<RenderRequest['layout']>
export type ShortStatus = ShortPick['status']
export type ShortDetail = components['schemas']['ShortDetail']
export type ShortVersion = components['schemas']['VersionOut']
export type ShortPage = components['schemas']['ShortPage']
export type ReviewAction = components['schemas']['ReviewRequest']['action']
export type Stats = components['schemas']['StatsOut']
export type ShortWords = components['schemas']['ShortWords']
export type StudioWord = components['schemas']['WordOut']
export type ContextSentence = components['schemas']['ContextSentence']
export type EditPlan = components['schemas']['EditOut']
export type SettingField = components['schemas']['SettingField']
export type SettingsPatch = components['schemas']['SettingsPatch']

export const mediaUrl = (assetId: string) => `/api/v1/media/${assetId}`

// Look up fetch at call time (not import time) so tests and polyfills can replace it.
// Absolute base URL: browsers accept relative URLs, but Request() outside a browser does not.
export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? '',
  fetch: (req) => globalThis.fetch(req),
})

export class ApiError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

/** Unwrap an openapi-fetch result or throw a readable error. */
export function unwrap<T>(r: { data?: T; error?: unknown; response: Response }): T {
  if (r.error !== undefined || r.data === undefined) {
    const detail = (r.error as { detail?: unknown } | undefined)?.detail
    let msg = `Request failed (${r.response.status})`
    if (typeof detail === 'string') msg = detail
    else if (Array.isArray(detail) && detail[0]?.msg) msg = String(detail[0].msg)
    else if (detail && typeof detail === 'object' && 'message' in detail)
      msg = String((detail as { message: unknown }).message)
    throw new ApiError(msg, r.response.status)
  }
  return r.data
}

export const FINAL_STATUSES: readonly JobStatus[] = ['succeeded', 'failed', 'cancelled']
