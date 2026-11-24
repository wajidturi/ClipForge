/** Toast messages for the results of actions (rendered by <Toaster />). */
import { create } from 'zustand'

type ToastTone = 'ok' | 'danger' | 'info'
type ToastItem = { id: number; tone: ToastTone; text: string }

let nextId = 1
export const useToasts = create<{
  items: ToastItem[]
  push: (tone: ToastTone, text: string) => void
  drop: (id: number) => void
}>((set) => ({
  items: [],
  push: (tone, text) => {
    const id = nextId++
    set((s) => ({ items: [...s.items.slice(-3), { id, tone, text }] }))
    setTimeout(() => set((s) => ({ items: s.items.filter((x) => x.id !== id) })), 5000)
  },
  drop: (id) => set((s) => ({ items: s.items.filter((x) => x.id !== id) })),
}))

/** Show the outcome of an action. Usable outside React (mutation callbacks). */
export const toast = {
  ok: (text: string) => useToasts.getState().push('ok', text),
  error: (text: string) => useToasts.getState().push('danger', text),
  info: (text: string) => useToasts.getState().push('info', text),
}
