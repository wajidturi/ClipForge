import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeQueryClient } from '@/lib/queryClient'
import { removeItem } from '@/lib/merge'
import { formatClock } from '@/lib/utils'
import { mockApi } from '@/test/fetchMock'
import { makeSource } from '@/test/fixtures'
import { Sources } from './Sources'

const READY = makeSource()
const FAILED = makeSource({
  id: '01900000-0000-7000-8000-0000000000bb',
  title: 'Private stream',
  status: 'failed',
  error: 'This video is private or for members only.',
  error_hint: 'Use a public video.',
})
const PLATFORMS = [
  { id: 'youtube', name: 'YouTube', example: '' },
  { id: 'twitch', name: 'Twitch', example: '' },
]

function setup(extra: Parameters<typeof mockApi>[0] = []) {
  const api = mockApi([
    ...extra,
    { method: 'GET', path: /\/sources\/platforms$/, handler: () => PLATFORMS },
    {
      method: 'GET',
      path: /\/sources$/,
      handler: () => ({ items: [READY, FAILED], next_cursor: null }),
    },
  ])
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter>
        <Sources />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return api
}

afterEach(() => vi.restoreAllMocks())

describe('Sources page', () => {
  it('lists sources with status, metadata and failure hints', async () => {
    setup()
    const rows = await screen.findAllByTestId('source-row')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('Huge reaction')).toBeInTheDocument()
    expect(within(rows[0]).getByText('Ready')).toBeInTheDocument()
    expect(within(rows[0]).getByText('Creator · YouTube · 1:02:03')).toBeInTheDocument()
    expect(within(rows[1]).getByText('Use a public video.')).toBeInTheDocument()
    expect(within(rows[1]).getByRole('button', { name: /retry/i })).toBeInTheDocument()
    expect(within(rows[0]).queryByRole('button', { name: /retry/i })).not.toBeInTheDocument()
  })

  it('filters by search text', async () => {
    setup()
    await screen.findAllByTestId('source-row')
    await userEvent.type(screen.getByLabelText(/search/i), 'private')
    expect(screen.getAllByTestId('source-row')).toHaveLength(1)
    expect(screen.getByText('Private stream')).toBeInTheDocument()
  })

  it('adds a link with an optional window', async () => {
    const api = setup([
      {
        method: 'POST',
        path: /\/sources$/,
        status: 201,
        handler: () => ({ source: READY, created: true, job_id: null }),
      },
    ])
    await userEvent.type(screen.getByLabelText('Video link'), 'https://youtu.be/dQw4w9WgXcQ')
    await userEvent.click(screen.getByLabelText(/only part/i))
    await userEvent.type(screen.getByLabelText('Start time'), '1:00')
    await userEvent.type(screen.getByLabelText('End time'), '2:00')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(await screen.findByText(/download started/i)).toBeInTheDocument()
    const post = api.calls.find((c) => c.method === 'POST')
    expect(post?.body).toEqual({ url: 'https://youtu.be/dQw4w9WgXcQ', start: '1:00', end: '2:00' })
  })

  it('shows the server message for a rejected link', async () => {
    setup([
      {
        method: 'POST',
        path: /\/sources$/,
        status: 422,
        handler: () => ({
          detail: 'this link is a channel or playlist; paste the link of one video',
        }),
      },
    ])
    await userEvent.type(screen.getByLabelText('Video link'), 'https://youtube.com/@x')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/channel or playlist/)
  })

  it('asks before deleting', async () => {
    const api = setup([
      { method: 'DELETE', path: /\/sources\/.+/, status: 204, handler: () => null },
    ])
    const rows = await screen.findAllByTestId('source-row')
    await userEvent.click(within(rows[0]).getByRole('button', { name: /^delete$/i }))
    expect(api.calls.some((c) => c.method === 'DELETE')).toBe(false)
    expect(within(rows[0]).getByText(/delete this source/i)).toBeInTheDocument()
    await userEvent.click(within(rows[0]).getByRole('button', { name: /^delete$/i }))
    await vi.waitFor(() => expect(api.calls.some((c) => c.method === 'DELETE')).toBe(true))
  })
})

describe('helpers', () => {
  it('formatClock', () => {
    expect(formatClock(3723)).toBe('1:02:03')
    expect(formatClock(65)).toBe('1:05')
    expect(formatClock(null)).toBe('–')
  })
  it('removeItem', () => {
    expect(removeItem({ items: [READY, FAILED], next_cursor: null }, READY.id)?.items).toEqual([
      FAILED,
    ])
    expect(removeItem(undefined, 'x')).toBeUndefined()
  })
})
