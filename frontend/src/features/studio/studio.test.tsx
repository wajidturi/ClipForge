import { QueryClientProvider } from '@tanstack/react-query'
import { act, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Layer, Scene } from '@/lib/api/client'
import { makeQueryClient } from '@/lib/queryClient'
import { useHistory } from '@/lib/studio'
import { Studio } from '@/pages/Studio'
import { mockApi } from '@/test/fetchMock'
import sceneJson from '@/test/scene.cinematic.json'
import { groupWords, layerAnim } from './compositor'
import { newLayer } from './library'
import { trackTargets, xAt, zoomAt } from './track'

// Values computed by backend reframe.track_targets for the same input.
const TARGETS: [number, number | null][] = [
  [0.0, 0.3],
  [0.25, 0.3795],
  [0.5, 0.4558],
  [0.75, null],
  [1.0, null],
  [1.25, 0.6366],
  [1.5, 0.6728],
  [1.75, 0.6942],
  [2.0, 0.6998],
  [2.25, 0.6895],
  [2.5, 0.6637],
  [2.75, 0.6234],
  [3.0, 0.5702],
  [3.25, 0.5062],
  [3.5, 0.434],
  [3.75, 0.3564],
  [4.0, 0.2767],
  [4.25, 0.1978],
  [4.5, 0.123],
  [4.75, 0.0553],
  [5.0, -0.0027],
  [5.25, -0.0486],
  [5.5, -0.0806],
  [5.75, -0.0975],
  [6.0, -0.0985],
  [6.25, -0.0836],
  [6.5, -0.0534],
  [6.75, -0.0091],
  [7.0, 0.0475],
  [7.25, 0.1142],
  [7.5, 0.1882],
  [7.75, 0.2668],
  [8.0, 0.3466],
  [8.25, 0.4246],
  [8.5, 0.4976],
  [8.75, 0.5628],
  [9.0, 0.6175],
  [9.25, 0.6595],
  [9.5, 0.6872],
  [9.75, 0.6994],
]
const PY_KEYS = [
  [0.0, 0.15],
  [0.5, 0.3058],
  [1.25, 0.3933],
  [1.5, 0.4808],
  [1.75, 0.5442],
  [2.75, 0.4734],
  [3.25, 0.3859],
  [4.0, 0.1267],
  [4.25, 0.0478],
  [4.5, 0.0],
  [5.0, 0.0],
  [7.75, 0.0875],
  [8.5, 0.3476],
  [8.75, 0.4128],
  [9.25, 0.5003],
]

describe('preview matches the renderer', () => {
  it('tracks the action exactly like the backend', () => {
    const keys = trackTargets(TARGETS, [5.0], 0.3)
    expect(keys.length).toBe(PY_KEYS.length)
    keys.forEach(([t, x], i) => {
      expect(t).toBeCloseTo(PY_KEYS[i]![0]!, 4)
      expect(x).toBeCloseTo(PY_KEYS[i]![1]!, 4)
    })
    expect(xAt(keys, 0.25)).toBeCloseTo(0.15 + (0.3058 - 0.15) / 2, 4)
    expect(xAt(keys, 99)).toBeCloseTo(0.5003, 4)
  })

  it('zooms and animates layers with the same formulas', () => {
    expect(zoomAt([5], 5.2, 0.12)).toBeCloseTo(1.12)
    expect(zoomAt([5], 4.9, 0.12)).toBeCloseTo(1.06)
    expect(zoomAt([5], 6.1, 0.12)).toBeCloseTo(1.06)
    const pop = newLayer({ start: 1, end: 3, anim_in: 'pop', anim_out: 'fade' })
    expect(layerAnim(pop, 1.11, 10).s).toBeCloseTo(0.725)
    expect(layerAnim(pop, 1.22, 10).s).toBeCloseTo(1.15)
    expect(layerAnim(pop, 2, 10).s).toBe(1)
    expect(layerAnim(pop, 1.06, 10).alpha).toBeCloseTo(0.5)
    expect(layerAnim(pop, 2.9, 10).alpha).toBeCloseTo(0.4)
    expect(layerAnim(pop, 3.1, 10).visible).toBe(false)
    const slide = newLayer({ anim_in: 'slide_up', start: 0 })
    expect(layerAnim(slide, 0, 10).dy).toBeCloseTo(220)
    expect(layerAnim(slide, 0.35, 10).dy).toBeCloseTo(0)
  })

  it('groups caption words like the ASS builder', () => {
    const w = (start: number, text: string) => ({ start, end: start + 0.3, text })
    const g = groupWords(
      [w(0, 'The'), w(0.4, 'bridge'), w(0.8, 'jump.'), w(2, 'No'), w(2.4, 'way!')],
      3,
    )
    expect(g.map((x) => x.words.map((y) => y.text))).toEqual([
      ['The', 'bridge', 'jump.'],
      ['No', 'way!'],
    ])
    expect(g[0]!.end).toBeCloseTo(1.7)
  })
})

describe('undo / redo', () => {
  it('records steps, groups a drag into one step and undoes it', () => {
    const { result } = renderHook(() => useHistory(0))
    act(() => result.current.set(1))
    act(() => result.current.set(2, true))
    act(() => result.current.set(3, true))
    act(() => result.current.commit())
    expect(result.current.value).toBe(3)
    act(() => result.current.undo())
    expect(result.current.value).toBe(1) // the whole drag
    act(() => result.current.undo())
    expect(result.current.value).toBe(0)
    expect(result.current.canUndo).toBe(false)
    act(() => result.current.redo())
    act(() => result.current.redo())
    expect(result.current.value).toBe(3)
  })
})

describe('Customisation studio', () => {
  afterEach(() => vi.restoreAllMocks())
  const scene = sceneJson as unknown as Scene
  const short = {
    id: 's1',
    run_id: null,
    source_id: 'src',
    format: 'moment',
    hook: 'BIG MOMENT',
    title: 't',
    hashtags: ['#shorts'],
    keywords: [],
    credit: 'me',
    score: 80,
    ai_reason: null,
    status: 'review',
    reject_reason: null,
    source_title: 'Stream',
    parts: [{ idx: 0, start_s: 10, end_s: 22, label: null }],
    has_preview: false,
    active: {
      id: 'v1',
      version_no: 1,
      origin: 'render',
      layout: 'cinematic',
      style: 'gaming',
      mp4_asset_id: 'mp4',
      cover_asset_id: null,
      extra_assets: {},
      qc_verdict: 'pass',
      qc_reasons: [],
      render_ms: 1,
      duration_s: 12,
    },
    render_job_id: null,
    created_at: '',
    updated_at: '',
    versions: [],
  }
  const options = {
    styles: [],
    templates: [
      ['streamer_first', 'Streamer First'],
      ['gameplay_first', 'Gameplay First'],
      ['dual_vision', 'Dual Vision'],
      ['floating_facecam', 'Floating Facecam'],
      ['cinematic', 'Cinematic Gaming'],
    ].map(([id, name]) => ({
      id,
      name,
      tagline: '',
      description: `${name} description`,
      needs_cam: false,
      controls: [],
    })),
    fonts: [{ id: 'impact', label: 'Impact', category: 'headline' }],
    caption_presets: { gaming: scene.captions },
    aspects: [],
    encoder: 'CPU (x264)',
  }

  it('adds a sticker, undoes it, and renders the customised scene', async () => {
    const api = mockApi([
      { method: 'GET', path: /\/shorts\/s1$/, handler: () => short },
      { method: 'GET', path: /\/render\/options$/, handler: () => options },
      { method: 'GET', path: /\/images$/, handler: () => [] },
      {
        method: 'GET',
        path: /\/shorts\/s1\/studio$/,
        handler: () => ({
          version_id: 'v1',
          scene,
          note: null,
          values: { hook: 'BIG MOMENT', channel: 'me', reaction: 'NO WAY!', title: 't' },
          caption_overrides: {},
          cut: {
            key: 'k',
            preview_asset_id: 'p',
            src_w: 1920,
            src_h: 1080,
            duration: 12,
            cam: null,
            targets: [[0, 0.5]],
            cuts: [],
            zoom_peaks: [5],
            words: [[0.5, 0.8, 'hello', '10.50']],
            reaction: 'NO WAY!',
          },
        }),
      },
      {
        method: 'POST',
        path: /\/shorts\/s1\/render$/,
        status: 202,
        handler: () => ({ job_ids: ['j'] }),
      },
    ])
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter initialEntries={['/shorts/s1']}>
          <Routes>
            <Route path="/shorts/:id" element={<Studio />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    // template-aware panel and template elements of the cinematic template
    expect(await screen.findByText('Cinematic Gaming description')).toBeInTheDocument()
    expect(screen.getByText('Cinematic title')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /cinematic gaming/i })).toHaveAttribute(
      'aria-checked',
      'true',
    )

    await userEvent.click(screen.getByRole('tab', { name: 'Add' }))
    await userEvent.click(screen.getByRole('button', { name: 'GG' }))
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument()
    const inspector = screen.getByRole('textbox', { name: 'Text' })
    expect(inspector).toHaveValue('GG')

    await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(screen.getByText('Matches the rendered video')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Redo' }))

    await userEvent.click(screen.getByRole('tab', { name: 'Effects' }))
    await userEvent.click(screen.getByRole('switch', { name: 'Cinema bars' }))

    await userEvent.click(screen.getByRole('button', { name: /render final video/i }))
    await waitFor(() => expect(api.calls.some((c) => c.method === 'POST')).toBe(true))
    const body = api.calls.find((c) => c.method === 'POST')!.body as {
      scene: Scene
      origin: string
    }
    expect(body.origin).toBe('manual_edit')
    expect(body.scene.effects.letterbox).toBe(true)
    const added = body.scene.layers.find((l: Layer) => l.text === 'GG')
    expect(added).toMatchObject({ role: 'user', anim_in: 'zoom', loop: 'pulse' })
    expect(within(document.body).queryByText('Undo')).toBeNull() // icon buttons, labelled only
  })
})
