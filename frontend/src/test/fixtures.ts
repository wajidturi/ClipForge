import type { Job, Source } from '@/lib/api/client'

export function makeSource(over: Partial<Source> = {}): Source {
  return {
    id: '01900000-0000-7000-8000-0000000000aa',
    platform: 'youtube',
    external_id: 'dQw4w9WgXcQ',
    url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    title: 'Huge reaction',
    channel_name: 'Creator',
    duration_s: 3723,
    published_at: null,
    language: null,
    window_start_s: null,
    window_end_s: null,
    status: 'ready',
    skip_reason: null,
    error: null,
    error_hint: null,
    latest_job_id: null,
    thumbnail: null,
    window_note: null,
    created_at: '2026-11-21T10:00:00Z',
    updated_at: '2026-11-21T10:00:04Z',
    ...over,
  }
}

export function makeJob(over: Partial<Job> = {}): Job {
  return {
    id: '01900000-0000-7000-8000-000000000001',
    parent_id: null,
    run_id: null,
    subject_type: null,
    subject_id: null,
    type: 'system.selftest',
    label: 'Self-test',
    status: 'running',
    progress: 40,
    step: 'step 4 of 10',
    attempts: 1,
    max_attempts: 3,
    cancel_requested: false,
    error: null,
    result: {},
    created_at: '2026-11-21T10:00:00Z',
    updated_at: '2026-11-21T10:00:04Z',
    started_at: '2026-11-21T10:00:01Z',
    finished_at: null,
    ...over,
  }
}
