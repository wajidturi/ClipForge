/**
 * One WebSocket per tab to /api/v1/ws. The server pushes job/source events; we
 * patch React Query's cache so every screen updates instantly without polling.
 * Reconnects with backoff, and refetches on reconnect to catch missed events.
 */
import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { create } from 'zustand'
import type { Job, Run, Source } from './api/client'
import { applyJobEvent, jobKeys } from './jobs'
import { applyRunEvent, applyShortEvent, runKeys } from './runs'
import { applySourceDeleted, applySourceEvent, sourceKeys } from './sources'

type ConnState = 'connecting' | 'open' | 'closed'

export const useConnection = create<{ state: ConnState; set: (s: ConnState) => void }>((set) => ({
  state: 'connecting',
  set: (state) => set({ state }),
}))

export type ServerEvent =
  | { type: 'job.updated'; job: Job }
  | { type: 'source.updated'; source: Source }
  | { type: 'source.deleted'; id: string }
  | { type: 'run.updated'; run: Run }
  | { type: 'short.updated'; id: string; run_id: string | null; status: string }
  | { type: 'ping' }

export function wsUrl(loc: Location = window.location): string {
  const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${loc.host}/api/v1/ws`
}

export function useServerEvents() {
  const qc = useQueryClient()
  const setState = useConnection((s) => s.set)

  useEffect(() => {
    let socket: WebSocket | null = null
    let retry = 0
    let timer: ReturnType<typeof setTimeout> | undefined
    let stopped = false

    const connect = () => {
      setState('connecting')
      socket = new WebSocket(wsUrl())
      socket.onopen = () => {
        if (retry > 0) {
          void qc.invalidateQueries({ queryKey: jobKeys.all })
          void qc.invalidateQueries({ queryKey: sourceKeys.all })
          void qc.invalidateQueries({ queryKey: runKeys.all })
        }
        retry = 0
        setState('open')
      }
      socket.onmessage = (e) => {
        try {
          const msg = JSON.parse(String(e.data)) as ServerEvent
          if (msg.type === 'job.updated') applyJobEvent(qc, msg.job)
          else if (msg.type === 'source.updated') applySourceEvent(qc, msg.source)
          else if (msg.type === 'source.deleted') applySourceDeleted(qc, msg.id)
          else if (msg.type === 'run.updated') applyRunEvent(qc, msg.run)
          else if (msg.type === 'short.updated') applyShortEvent(qc, msg)
        } catch {
          /* ignore malformed frames */
        }
      }
      socket.onclose = () => {
        setState('closed')
        if (stopped) return
        retry += 1
        timer = setTimeout(connect, Math.min(10_000, 500 * 2 ** retry))
      }
    }

    connect()
    return () => {
      stopped = true
      clearTimeout(timer)
      socket?.close()
    }
  }, [qc, setState])
}
