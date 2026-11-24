import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Toaster } from '@/components/feedback'
import { makeQueryClient } from '@/lib/queryClient'
import { mockApi } from '@/test/fetchMock'
import { makeJob } from '@/test/fixtures'
import { Jobs } from './Jobs'

const running = makeJob({ id: 'j1', label: 'Render: NO WAY' })
const queued = makeJob({ id: 'j2', label: 'Analyse stream', status: 'queued', progress: 0 })
const done = makeJob({
  id: 'j3',
  label: 'Old render',
  status: 'succeeded',
  progress: 100,
  finished_at: '2026-11-21T10:00:05Z',
})

function renderJobs() {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter>
        <Jobs />
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('Jobs page', () => {
  it('separates running jobs from the history', async () => {
    mockApi([
      { method: 'GET', path: /\/jobs$/, handler: () => ({ items: [running, queued, done] }) },
    ])
    renderJobs()
    await screen.findByText('Render: NO WAY')
    const active = screen.getByText('Running now').closest('div.rounded-xl')!
    expect(within(active as HTMLElement).getByText('Render: NO WAY')).toBeInTheDocument()
    expect(within(active as HTMLElement).getByText('Analyse stream')).toBeInTheDocument()
    expect(within(active as HTMLElement).queryByText('Old render')).not.toBeInTheDocument()
    const history = screen.getByText('History').closest('div.rounded-xl')!
    expect(within(history as HTMLElement).getByText('Old render')).toBeInTheDocument()
  })

  it('stops all jobs only after confirming', async () => {
    const api = mockApi([
      { method: 'GET', path: /\/jobs$/, handler: () => ({ items: [running, queued, done] }) },
      { method: 'POST', path: /\/jobs\/cancel-all$/, handler: () => ({ count: 2 }) },
    ])
    renderJobs()
    await userEvent.click(await screen.findByRole('button', { name: 'Stop all' }))
    const dialog = screen.getByRole('alertdialog', { name: 'Stop all 2 jobs?' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(api.calls.some((c) => c.path.endsWith('/cancel-all'))).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: 'Stop all' }))
    await userEvent.click(
      within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Stop all' }),
    )
    await waitFor(() =>
      expect(api.calls.some((c) => c.method === 'POST' && c.path.endsWith('/cancel-all'))).toBe(
        true,
      ),
    )
    expect(await screen.findByText('Stopped 2 jobs')).toBeInTheDocument()
  })

  it('clears the history after confirming', async () => {
    const api = mockApi([
      { method: 'GET', path: /\/jobs$/, handler: () => ({ items: [running, done] }) },
      { method: 'DELETE', path: /\/jobs\/history$/, handler: () => ({ count: 1 }) },
    ])
    renderJobs()
    await userEvent.click(await screen.findByRole('button', { name: 'Clear history' }))
    const dialog = screen.getByRole('alertdialog', { name: 'Clear the job history?' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Clear history' }))
    await waitFor(() =>
      expect(api.calls.some((c) => c.method === 'DELETE' && c.path.endsWith('/history'))).toBe(
        true,
      ),
    )
    expect(await screen.findByText('Removed 1 job from the history')).toBeInTheDocument()
  })
})
