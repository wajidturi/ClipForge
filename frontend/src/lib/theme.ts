import { create } from 'zustand'
import { safeStorage } from './utils'

export type Theme = 'dark' | 'light'

const initial: Theme = safeStorage.get('cf.theme') === 'light' ? 'light' : 'dark'

function apply(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}
apply(initial)

export const useTheme = create<{ theme: Theme; toggle: () => void }>((set, get) => ({
  theme: initial,
  toggle: () => {
    const theme: Theme = get().theme === 'dark' ? 'light' : 'dark'
    apply(theme)
    safeStorage.set('cf.theme', theme)
    set({ theme })
  },
}))
