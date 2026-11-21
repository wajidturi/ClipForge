import { QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Timeline, TranscriptSegment } from '@/lib/api/client'
import { makeQueryClient } from '@/lib/queryClient'
import { SourceDetail } from '@/pages/SourceDetail'
import { mockApi } from '@/test/fetchMock'
import { makeSource } from '@/test/fixtures'
import { TimelineGraph } from './TimelineGraph'
import { activeIndex } from './markers'
import { TranscriptView } from './TranscriptView'

const SEGS: TranscriptSegment[] = [
  {
    idx: 0,
    start_s: 10,
    end_s: 12,
    text: 'The car crashed.',
    heat: 72,
    tags: [{ type: 'LOUD', label: '+18 dB', score: 1 }],
  },
  {
    idx: 1,
    start_s: 13,
    end_s: 15,
    text: 'Ha ha ha!',
    heat: 30,
    tags: [{ type: 'LAUGH', label: 'laughter', score: 0.7 }],
  },
  { idx: 2, start_s: 20, end_s: 22, text: 'Back to the plan.', heat: 0, tags: [] },
]

const TIMELINE: Timeline = {
  start_s: 0,
  end_s: 100,
  bins: 4,
  heat: [0, 72, 30, 0],
  loud: [0.1, 1, 0.2, 0.1],
  chat: [0, 0, 0, 0],
  motion: [0, 0, 0, 0],
  replay: [0, 0, 0, 0],
  markers: [{ type: 'loud', start_s: 10, end_s: 12, score: 1, label: '+18 dB' }],
  available: ['loud', 'moment', 'laugh'],
  steps: { transcribe: 'done (cuda, small)', loudness: 'done' },
  warnings: ['faces: model download failed; motion only'],
}

afterEach(() => vi.restoreAllMocks())

describe('activeIndex', () => {
  it('finds the sentence playing now', () => {
    expect(activeIndex(SEGS, 11)).toBe(0)
    expect(activeIndex(SEGS, 14)).toBe(1)
    expect(activeIndex(SEGS, 18)).toBe(-1) // a gap between sentences
    expect(activeIndex(SEGS, 5)).toBe(-1)
    expect(activeIndex(SEGS, null)).toBe(-1)
  })
})

describe('TranscriptView', () => {
  it('shows tags, highlights the active line, seeks on click and filters', async () => {
    const onSeek = vi.fn()
    render(<TranscriptView segments={SEGS} now={14} onSeek={onSeek} />)
    const rows = screen.getAllByTestId('segment')
    expect(rows).toHaveLength(3)
    expect(within(rows[0]).getByText('LOUD · +18 dB')).toBeInTheDocument()
    expect(rows[1].className).toContain('border-accent')
    await userEvent.click(rows[2])
    expect(onSeek).toHaveBeenCalledWith(20)
    await userEvent.click(screen.getByLabelText(/only hot/i))
    expect(screen.getAllByTestId('segment')).toHaveLength(1)
    await userEvent.click(screen.getByLabelText(/only hot/i))
    await userEvent.type(screen.getByLabelText(/search the transcript/i), 'plan')
    expect(screen.getAllByTestId('segment').map((r) => r.textContent)).toEqual([
      expect.stringContaining('Back to the plan.'),
    ])
  })
})

describe('TimelineGraph', () => {
  it('draws markers and converts a click into a video time', () => {
    const onSeek = vi.fn()
    render(<TimelineGraph data={TIMELINE} now={50} onSeek={onSeek} />)
    expect(screen.getAllByTestId('marker')).toHaveLength(1)
    const svg = screen.getByRole('img')
    svg.getBoundingClientRect = () => ({ left: 100, width: 400 }) as DOMRect
    fireEvent.click(svg, { clientX: 300 })
    expect(onSeek).toHaveBeenCalledWith(50) // halfway through 0-100 s
    // only layers with data get a toggle
    expect(screen.getByLabelText('Loudness')).toBeInTheDocument()
    expect(screen.queryByLabelText('Chat speed')).not.toBeInTheDocument()
  })
})

describe('SourceDetail page', () => {
  it('shows transcript, analysis steps and warnings for a ready source', async () => {
    const src = {
      ...makeSource({ window_start_s: 0 }),
      assets: [],
      chapters: [],
      has_heatmap: false,
    }
    src.assets = [
      {
        id: 'a1',
        kind: 'audio',
        bytes: 1,
        duration_s: 100,
        width: null,
        height: null,
        codec: 'aac',
        created_at: '',
      },
    ] as never
    mockApi([
      {
        method: 'GET',
        path: /\/transcript$/,
        handler: () => ({
          language: 'en',
          language_prob: 1,
          model: 'small',
          device: 'cuda',
          word_count: 9,
          segments: SEGS,
        }),
      },
      { method: 'GET', path: /\/timeline$/, handler: () => TIMELINE },
      { method: 'GET', path: /\/sources\/[^/]+$/, handler: () => src },
    ])
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter initialEntries={[`/sources/${src.id}`]}>
          <Routes>
            <Route path="/sources/:id" element={<SourceDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByText('Huge reaction')).toBeInTheDocument()
    expect(await screen.findAllByTestId('segment')).toHaveLength(3)
    expect(screen.getByText('done (cuda, small)')).toBeInTheDocument()
    expect(screen.getByText(/model download failed/)).toBeInTheDocument()
    expect(screen.getByText(/small · CUDA · 9 words/)).toBeInTheDocument()
    expect(document.querySelector('audio')?.getAttribute('src')).toBe('/api/v1/media/a1')
  })
})
