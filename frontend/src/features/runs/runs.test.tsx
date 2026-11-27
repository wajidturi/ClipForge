import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RunDetail as Detail, ShortPick } from '@/lib/api/client'
import { makeQueryClient } from '@/lib/queryClient'
import { Create } from '@/pages/Create'
import { RunDetail } from '@/pages/RunDetail'
import { mockApi } from '@/test/fetchMock'
import { makeSource } from '@/test/fixtures'

const READY = makeSource()
const BUSY = makeSource({
  id: '01900000-0000-7000-8000-0000000000cc',
  title: 'Still analysing',
  status: 'analyzing',
})
const RUN_ID = '01900000-0000-7000-8000-00000000r001'
const TEMPLATES = [
  ['streamer_first', 'Streamer First'],
  ['gameplay_first', 'Gameplay First'],
  ['dual_vision', 'Dual Vision'],
  ['floating_facecam', 'Floating Facecam'],
  ['cinematic', 'Cinematic Gaming'],
].map(([id, name]) => ({ id, name, tagline: '', description: '', needs_cam: false, controls: [] }))

const PICK: ShortPick = {
  id: 's1',
  run_id: RUN_ID,
  source_id: READY.id,
  format: 'moment',
  hook: 'KAI JUMPS THE BRIDGE',
  title: 'Kai Cenat jumps the bridge',
  hashtags: ['#gta6', '#shorts'],
  keywords: ['BRIDGE'],
  credit: 'Kai Cenat',
  score: 88,
  ai_reason: 'clear payoff',
  status: 'picked',
  parts: [{ idx: 0, start_s: 130, end_s: 164, label: null }],
  has_preview: false,
  created_at: '',
  updated_at: '',
}
const RUN: Detail = {
  id: RUN_ID,
  status: 'succeeded',
  params: { n: 2, pick_mode: 'smart', topic: 'GTA 6' },
  ai_provider: 'ollama',
  ai_model: 'qwen3.5:4b',
  ai_usage: { input_tokens: 900, output_tokens: 100, seconds: 12 },
  result: {
    warnings: ['AI picked 1 usable moments; 1 added by signal score'],
    rejected: [],
    callbacks: [],
  },
  error: null,
  created_at: '',
  updated_at: '',
  started_at: null,
  finished_at: null,
  shorts: [PICK],
  candidates: [],
  job_id: null,
}

function renderAt(path: string) {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/create" element={<Create />} />
          <Route path="/runs/:id" element={<RunDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('Create page', () => {
  it('offers only analysed sources and starts a run', async () => {
    const api = mockApi([
      {
        method: 'GET',
        path: /\/sources$/,
        handler: () => ({ items: [READY, BUSY], next_cursor: null }),
      },
      { method: 'GET', path: /\/runs$/, handler: () => [] },
      {
        method: 'GET',
        path: /\/ai\/status$/,
        handler: () => ({
          provider: 'ollama',
          model: 'qwen3.5:4b',
          ok: true,
          detail: 'Ollama ready, model qwen3.5:4b',
          models: [],
        }),
      },
      {
        method: 'GET',
        path: /\/render\/options$/,
        handler: () => ({
          styles: [],
          templates: TEMPLATES,
          fonts: [],
          caption_presets: {},
          aspects: [],
          encoder: 'CPU (x264)',
        }),
      },
      { method: 'POST', path: /\/runs$/, status: 201, handler: () => RUN },
      { method: 'GET', path: /\/runs\/.+/, handler: () => RUN },
    ])
    renderAt('/create')
    expect(await screen.findByText('Huge reaction')).toBeInTheDocument()
    expect(screen.queryByText('Still analysing')).not.toBeInTheDocument()
    expect(await screen.findByText('Ollama ready, model qwen3.5:4b')).toBeInTheDocument()
    const start = screen.getByRole('button', { name: /pick 5 moments and generate/i })
    expect(start).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: /huge reaction/i }))
    await userEvent.click(await screen.findByRole('radio', { name: /cinematic gaming/i }))
    await userEvent.click(screen.getByRole('radio', { name: /deep/i }))
    await userEvent.click(screen.getByRole('radio', { name: /whole scenes/i }))
    await userEvent.type(screen.getByLabelText('Topic'), 'GTA 6')
    await userEvent.type(screen.getByLabelText('From'), '5:00')
    await userEvent.type(screen.getByLabelText('To'), '11:00')
    await userEvent.click(start)
    expect(await screen.findByText('KAI JUMPS THE BRIDGE')).toBeInTheDocument() // navigated to the run
    const post = api.calls.find((c) => c.method === 'POST')
    expect(post?.body).toEqual({
      source_ids: [READY.id],
      n: 5,
      pick_mode: 'deep',
      topic: 'GTA 6',
      length: 'long',
      render: {
        template: 'cinematic',
        aspects: [],
        canvas: { preset: '9:16', w: 1080, h: 1920 },
      },
      start: '5:00',
      end: '11:00',
    })
  })
})

describe('Run page', () => {
  it('shows picks with warnings and edits a pick', async () => {
    const api = mockApi([
      { method: 'PATCH', path: /\/shorts\/s1$/, handler: () => PICK },
      { method: 'GET', path: /\/runs\/.+/, handler: () => RUN },
    ])
    renderAt(`/runs/${RUN_ID}`)
    const card = await screen.findByTestId('pick')
    expect(within(card).getByText('2:10 – 2:44 · 34s')).toBeInTheDocument()
    expect(within(card).getByText('88')).toBeInTheDocument()
    expect(screen.getByText(/1 added by signal score/)).toBeInTheDocument()
    expect(screen.getByText(/qwen3.5:4b · Topic: GTA 6 · 12s · 1000 tokens/)).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: /watch/i })).toHaveAttribute(
      'href',
      `/sources/${READY.id}?t=130.0`,
    )
    await userEvent.click(within(card).getByRole('button', { name: /edit/i }))
    const hook = within(card).getByLabelText('Hook')
    await userEvent.clear(hook)
    await userEvent.type(hook, 'new hook')
    const start = within(card).getByLabelText('Start')
    await userEvent.clear(start)
    await userEvent.type(start, '2:00')
    await userEvent.click(within(card).getByRole('button', { name: /save/i }))
    await vi.waitFor(() => expect(api.calls.some((c) => c.method === 'PATCH')).toBe(true))
    const patch = api.calls.find((c) => c.method === 'PATCH')
    expect(patch?.body).toEqual({
      hook: 'new hook',
      title: 'Kai Cenat jumps the bridge',
      start_s: 120,
    })
  })
})

describe('Rendered pick', () => {
  it('shows the player and QC, leads to the studio, renders again with the template', async () => {
    const rendered: ShortPick = {
      ...PICK,
      status: 'review',
      active: {
        id: 'v1',
        version_no: 1,
        origin: 'render',
        layout: 'crop',
        style: 'classic',
        mp4_asset_id: 'mp4-1',
        cover_asset_id: 'cov-1',
        extra_assets: { '4:5': 'ar-1' },
        qc_verdict: 'warn',
        qc_reasons: ['loudness -16.0 LUFS (target -14)'],
        render_ms: 12000,
        duration_s: 15.6,
      },
    }
    const api = mockApi([
      {
        method: 'POST',
        path: /\/shorts\/s1\/render$/,
        status: 202,
        handler: () => ({ job_ids: ['j1'] }),
      },
      {
        method: 'GET',
        path: /\/render\/options$/,
        handler: () => ({
          styles: [{ id: 'classic', label: 'Classic' }],
          templates: TEMPLATES,
          fonts: [],
          caption_presets: {},
          aspects: [],
          encoder: 'CPU (x264)',
        }),
      },
      { method: 'GET', path: /\/runs\/.+/, handler: () => ({ ...RUN, shorts: [rendered] }) },
    ])
    renderAt(`/runs/${RUN_ID}`)
    const card = await screen.findByTestId('pick')
    expect(within(card).getByLabelText('Rendered Short')).toHaveAttribute(
      'src',
      '/api/v1/media/mp4-1',
    )
    expect(within(card).getByText('QC warnings')).toBeInTheDocument()
    expect(within(card).getByText(/loudness -16.0 LUFS/)).toBeInTheDocument()
    // no direct download: the next step is the review & customisation studio
    expect(within(card).queryByRole('link', { name: 'MP4' })).not.toBeInTheDocument()
    expect(within(card).getByRole('link', { name: /review & customise/i })).toHaveAttribute(
      'href',
      '/shorts/s1',
    )
    await screen.findByText('Encoder: CPU (x264)')
    await userEvent.click(screen.getByRole('radio', { name: /dual vision/i }))
    await userEvent.click(within(card).getByRole('button', { name: /render again/i }))
    await vi.waitFor(() => expect(api.calls.some((c) => c.method === 'POST')).toBe(true))
    expect(api.calls.find((c) => c.method === 'POST')?.body).toEqual({
      template: 'dual_vision',
      aspects: [],
    })
  })
})
