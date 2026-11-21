import { describe, expect, it } from 'vitest'
import { makeJob } from '@/test/fixtures'
import { mergeJob } from './jobs'
import { wsUrl } from './events'

describe('mergeJob', () => {
  it('adds a new job on top', () => {
    const a = makeJob({ id: 'a' })
    const b = makeJob({ id: 'b' })
    expect(mergeJob({ items: [a], next_cursor: null }, b).items.map((j) => j.id)).toEqual([
      'b',
      'a',
    ])
  })

  it('replaces an existing job with newer data', () => {
    const old = makeJob({ progress: 10, updated_at: '2026-11-21T10:00:01Z' })
    const fresh = makeJob({ progress: 90, updated_at: '2026-11-21T10:00:09Z' })
    const page = mergeJob({ items: [old], next_cursor: 'x' }, fresh)
    expect(page.items).toHaveLength(1)
    expect(page.items[0].progress).toBe(90)
    expect(page.next_cursor).toBe('x')
  })

  it('ignores out-of-order older events', () => {
    const fresh = makeJob({ status: 'succeeded', updated_at: '2026-11-21T10:00:09Z' })
    const stale = makeJob({ status: 'running', updated_at: '2026-11-21T10:00:02Z' })
    expect(mergeJob({ items: [fresh], next_cursor: null }, stale).items[0].status).toBe('succeeded')
  })

  it('works on an empty cache', () => {
    expect(mergeJob(undefined, makeJob()).items).toHaveLength(1)
  })
})

describe('wsUrl', () => {
  it('uses wss on https', () => {
    expect(wsUrl({ protocol: 'https:', host: 'x.test' } as Location)).toBe('wss://x.test/api/v1/ws')
    expect(wsUrl({ protocol: 'http:', host: 'localhost:5173' } as Location)).toBe(
      'ws://localhost:5173/api/v1/ws',
    )
  })
})
