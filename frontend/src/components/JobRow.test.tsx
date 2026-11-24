import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeQueryClient } from '@/lib/queryClient'
import { makeJob } from '@/test/fixtures'
import { JobRow } from './JobRow'

function renderRow(job = makeJob()) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <ul>
        <JobRow job={job} />
      </ul>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('JobRow', () => {
  it('shows a running job with progress and a stop button', () => {
    renderRow()
    expect(screen.getByText('Self-test')).toBeInTheDocument()
    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40')
    expect(screen.getByRole('button', { name: /stop/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument()
  })

  it('shows the first error line and a retry button for failed jobs', () => {
    renderRow(
      makeJob({
        status: 'failed',
        error: 'disk full\nTraceback...',
        finished_at: '2026-11-21T10:00:05Z',
      }),
    )
    expect(screen.getByText('disk full')).toBeInTheDocument()
    expect(screen.queryByText(/Traceback/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('shows a job that is being stopped without a second stop button', () => {
    renderRow(makeJob({ cancel_requested: true }))
    expect(screen.getAllByText('Stopping…').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /stop/i })).not.toBeInTheDocument()
  })

  it('calls the cancel endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(makeJob({ cancel_requested: true })), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    renderRow()
    await userEvent.click(screen.getByRole('button', { name: /stop/i }))
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    const req = fetchMock.mock.calls[0][0] as Request
    expect(req.method).toBe('POST')
    expect(req.url).toMatch(/\/api\/v1\/jobs\/.+\/cancel$/)
  })
})
