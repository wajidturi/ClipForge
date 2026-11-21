import type { TranscriptSegment } from '@/lib/api/client'

/** Sentences at or above this heat count as "hot". */
export const HOT = 40

/** Index of the segment playing at `t` (segments are sorted by start), or -1. */
export function activeIndex(segments: TranscriptSegment[], t: number | null): number {
  if (t == null) return -1
  let lo = 0
  let hi = segments.length - 1
  let found = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (segments[mid].start_s <= t) {
      found = mid
      lo = mid + 1
    } else hi = mid - 1
  }
  return found >= 0 && t <= segments[found].end_s + 0.5 ? found : -1
}

/** Colours and names shared by the timeline, legend and transcript tags. */
export const SIGNAL_STYLE: Record<string, { color: string; key: string }> = {
  loud: { color: '#f59e0b', key: 'loud' },
  chat_spike: { color: '#8b7fff', key: 'chat' },
  clip: { color: '#ec4899', key: 'clip' },
  replay: { color: '#22c55e', key: 'replay' },
  moment: { color: '#38bdf8', key: 'moment' },
  banner: { color: '#ef4444', key: 'banner' },
  laugh: { color: '#eab308', key: 'laugh' },
}

/** Transcript tag type (LOUD, CHAT, ...) -> signal type. */
export const TAG_TO_SIGNAL: Record<string, string> = {
  LOUD: 'loud',
  CHAT: 'chat_spike',
  CLIPPED: 'clip',
  REPLAYED: 'replay',
  MOMENT: 'moment',
  GAME: 'banner',
  LAUGH: 'laugh',
}

/** 0-100 heat -> colour from cool to hot. */
export function heatColor(heat: number): string {
  if (heat >= 70) return '#ef4444'
  if (heat >= 45) return '#f97316'
  if (heat >= 20) return '#eab308'
  if (heat > 0) return '#64748b'
  return 'transparent'
}
