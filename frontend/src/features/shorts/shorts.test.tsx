import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SettingField, ShortDetail, ShortPick } from '@/lib/api/client'
import { makeQueryClient } from '@/lib/queryClient'
import { Library } from '@/pages/Library'
import { Review } from '@/pages/Review'
import { Settings } from '@/pages/Settings'
import { Studio } from '@/pages/Studio'
import { mockApi } from '@/test/fetchMock'

const ACTIVE = {
  id: 'v1',
  version_no: 1,
  origin: 'render',
  layout: 'crop',
  style: 'classic',
  mp4_asset_id: 'a1',
  cover_asset_id: 'a2',
  extra_assets: {},
  qc_verdict: 'pass',
  qc_reasons: [],
  render_ms: 9000,
  duration_s: 31,
}

function makeShort(over: Partial<ShortPick> = {}): ShortPick {
  return {
    id: 's1',
    run_id: 'r1',
    source_id: 'src1',
    format: 'moment',
    hook: 'HE DID NOT SEE THAT',
    title: 'The jump nobody expected',
    hashtags: ['#gta', '#shorts'],
    keywords: ['JUMP'],
    credit: 'Creator',
    score: 80,
    ai_reason: null,
    status: 'review',
    reject_reason: null,
    source_title: 'Long stream',
    parts: [{ idx: 0, start_s: 100, end_s: 131, label: null }],
    has_preview: false,
    active: ACTIVE,
    render_job_id: null,
    created_at: '2026-11-22T10:00:00Z',
    updated_at: '2026-11-22T10:00:00Z',
    ...over,
  }
}

function page(items: ShortPick[]) {
  return { items, next_cursor: null, total: items.length }
}

function renderAt(path: string) {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/shorts" element={<Library />} />
          <Route path="/shorts/:id" element={<Studio />} />
          <Route path="/review" element={<Review />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('Library', () => {
  it('lists Shorts, filters by tab and bulk-approves the selection', async () => {
    const a = makeShort()
    const b = makeShort({ id: 's2', hook: 'SECOND ONE', active: null, status: 'picked' })
    const api = mockApi([
      { method: 'GET', path: /\/shorts$/, handler: () => page([a, b]) },
      {
        method: 'POST',
        path: /\/shorts\/review$/,
        handler: () => ({ updated: ['s1'], skipped: [] }),
      },
    ])
    renderAt('/shorts')
    const tiles = await screen.findAllByTestId('short-tile')
    expect(tiles).toHaveLength(2)
    expect(within(tiles[0]!).getByText('Long stream · 31s')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'To review' }))
    await waitFor(() =>
      expect(api.calls.some((c) => c.path.endsWith('/shorts') && c.method === 'GET')).toBe(true),
    )
    const urls = api.spy.mock.calls.map((c) => String((c[0] as Request).url))
    await waitFor(() => expect(urls.some((u) => u.includes('status=review'))).toBe(true))

    const fresh = await screen.findAllByTestId('short-tile') // re-rendered for the new filter
    await userEvent.click(within(fresh[0]!).getByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: /Approve/ }))
    await waitFor(() =>
      expect(api.calls.find((c) => c.path.endsWith('/shorts/review'))?.body).toEqual({
        short_ids: ['s1'],
        action: 'approve',
        reason: null,
      }),
    )
  })
})

describe('Review queue', () => {
  it('approves with the A key and rejects with a reason', async () => {
    const api = mockApi([
      { method: 'GET', path: /\/shorts$/, handler: () => page([makeShort()]) },
      {
        method: 'POST',
        path: /\/shorts\/s1\/review$/,
        handler: () => makeShort({ status: 'approved' }),
      },
    ])
    renderAt('/review')
    expect(await screen.findByText('HE DID NOT SEE THAT')).toBeInTheDocument()
    expect(screen.getByText('1 of 1')).toBeInTheDocument()

    await userEvent.keyboard('a')
    await waitFor(() =>
      expect(api.calls.find((c) => c.path.endsWith('/s1/review'))?.body).toEqual({
        action: 'approve',
        reason: null,
      }),
    )

    await userEvent.keyboard('r')
    const reason = await screen.findByRole('textbox', { name: 'Reason' })
    await userEvent.type(reason, 'too quiet{Enter}')
    await waitFor(() =>
      expect(api.calls.filter((c) => c.path.endsWith('/s1/review'))[1]?.body).toEqual({
        action: 'reject',
        reason: 'too quiet',
      }),
    )
  })

  it('says when nothing is waiting', async () => {
    mockApi([{ method: 'GET', path: /\/shorts$/, handler: () => page([]) }])
    renderAt('/review')
    expect(await screen.findByText(/All caught up/)).toBeInTheDocument()
  })
})

describe('Studio', () => {
  const detail: ShortDetail = {
    ...makeShort(),
    versions: [
      { ...ACTIVE, created_at: '', qc_checks: {}, settings: { style: 'classic' } },
      {
        ...ACTIVE,
        id: 'v0',
        version_no: 0,
        mp4_asset_id: 'a0',
        created_at: '',
        qc_checks: {},
        settings: {},
      },
    ],
  }

  it('plans an AI edit, shows the operations and applies it', async () => {
    const plan = {
      id: 'e1',
      short_id: 's1',
      kind: 'ai',
      instruction: 'Make the hook punchier',
      status: 'planned',
      error: null,
      base_version_id: 'v1',
      result_version_id: null,
      created_at: '',
      plan: {
        summary: 'A punchier hook',
        ops: [{ op: 'set_hook', text: 'NO WAY HE JUMPED' }],
        notes: [],
      },
    }
    const api = mockApi([
      { method: 'GET', path: /\/shorts\/s1$/, handler: () => detail },
      { method: 'GET', path: /\/shorts\/s1\/edits$/, handler: () => [] },
      { method: 'POST', path: /\/shorts\/s1\/ai-edit$/, handler: () => plan },
      {
        method: 'POST',
        path: /\/edits\/e1\/apply$/,
        handler: () => ({
          edit: { ...plan, status: 'applied' },
          short: makeShort({ status: 'rendering' }),
          job_id: 'j1',
        }),
      },
    ])
    renderAt('/shorts/s1?tab=ai')
    await userEvent.click(await screen.findByRole('button', { name: 'Make the hook punchier' }))
    await userEvent.click(screen.getByRole('button', { name: /Suggest the edit/ }))
    const box = await screen.findByTestId('edit-plan')
    expect(within(box).getByText('A punchier hook')).toBeInTheDocument()
    expect(within(box).getByText('NO WAY HE JUMPED')).toBeInTheDocument()
    expect(api.calls.find((c) => c.path.endsWith('/ai-edit'))?.body).toEqual({
      instruction: 'Make the hook punchier',
    })
    await userEvent.click(within(box).getByRole('button', { name: /Apply/ }))
    expect(await within(box).findByText(/new version is rendering/)).toBeInTheDocument()
  })

  it('lists versions and saves post texts', async () => {
    const api = mockApi([
      { method: 'GET', path: /\/shorts\/s1$/, handler: () => detail },
      { method: 'PATCH', path: /\/shorts\/s1$/, handler: () => makeShort({ title: 'New' }) },
    ])
    renderAt('/shorts/s1?tab=post')
    expect(await screen.findByText('Versions')).toBeInTheDocument()
    const title = screen.getByRole('textbox', { name: /Title/ })
    await userEvent.clear(title)
    await userEvent.type(title, 'New')
    await userEvent.click(screen.getByRole('button', { name: /Save/ }))
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({ title: 'New' }),
    )
  })
})

describe('Settings', () => {
  const fields: SettingField[] = [
    {
      key: 'ai_provider',
      section: 'ai',
      kind: 'choice',
      nullable: false,
      choices: ['ollama', 'none'],
      min: null,
      max: null,
      value: 'ollama',
      default: 'ollama',
      overridden: false,
    },
    {
      key: 'candidates_k',
      section: 'ai',
      kind: 'int',
      nullable: false,
      choices: null,
      min: 5,
      max: 120,
      value: 40,
      default: 30,
      overridden: true,
    },
    {
      key: 'auto_render',
      section: 'render',
      kind: 'bool',
      nullable: false,
      choices: null,
      min: null,
      max: null,
      value: false,
      default: false,
      overridden: false,
    },
  ]

  it('saves only changed values and resets overridden ones', async () => {
    const api = mockApi([
      { method: 'GET', path: /\/settings$/, handler: () => ({ fields }) },
      { method: 'PATCH', path: /\/settings$/, handler: () => ({ fields }) },
      {
        method: 'GET',
        path: /\/ai\/status$/,
        handler: () => ({ provider: 'ollama', model: 'm', ok: true, detail: 'ready', models: [] }),
      },
    ])
    renderAt('/settings')
    await userEvent.click(await screen.findByLabelText('Render picks automatically'))
    expect(screen.getByText('1 unsaved changes')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^Save$/ }))
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === 'PATCH')?.body).toEqual({
        values: { auto_render: true },
        reset: [],
      }),
    )
    await userEvent.click(screen.getByRole('button', { name: /Use default/ }))
    await waitFor(() =>
      expect(api.calls.filter((c) => c.method === 'PATCH')[1]?.body).toEqual({
        values: {},
        reset: ['candidates_k'],
      }),
    )
  })
})
