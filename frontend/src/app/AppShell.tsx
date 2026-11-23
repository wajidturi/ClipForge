import { Moon, Sun } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Navigate, NavLink, Outlet } from 'react-router'
import { useConnection, useServerEvents } from '@/lib/events'
import { settingValue, useSettings } from '@/lib/settings'
import { useStats } from '@/lib/shorts'
import { useTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'
import { NAV } from './nav'

function ConnectionDot() {
  const { t } = useTranslation()
  const state = useConnection((s) => s.state)
  const color = { open: 'bg-ok', connecting: 'bg-warn', closed: 'bg-danger' }[state]
  return (
    <div className="flex items-center gap-2 text-xs text-muted" role="status">
      <span className={cn('size-2 rounded-full', color)} aria-hidden />
      {t(`conn.${state}`)}
    </div>
  )
}

export function AppShell() {
  const { t } = useTranslation()
  const { theme, toggle } = useTheme()
  useServerEvents()
  const settings = useSettings()
  const stats = useStats()
  const toReview = stats.data?.shorts.review ?? 0
  // First run: show the setup wizard once (it sets `onboarded`).
  if (settings.data && settingValue<boolean>(settings.data, 'onboarded') === false)
    return <Navigate to="/welcome" replace />

  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-surface">
        <div className="flex h-14 items-center gap-2.5 px-5">
          <img src="/favicon.svg" alt="" className="size-6" />
          <span className="font-semibold tracking-tight">{t('app.name')}</span>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-2" aria-label="Main">
          {NAV.map(({ to, key, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition',
                  isActive
                    ? 'bg-accent/12 font-medium text-accent'
                    : 'text-muted hover:bg-surface-2 hover:text-fg',
                )
              }
            >
              <Icon size={17} aria-hidden />
              <span className="flex-1">{t(`nav.${key}`)}</span>
              {key === 'review' && toReview > 0 && (
                <span className="rounded-full bg-accent px-1.5 text-[10px] font-semibold text-accent-fg tabular-nums">
                  {toReview}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center justify-between border-t border-border px-5 py-3">
          <ConnectionDot />
          <button
            onClick={toggle}
            className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-fg"
            aria-label={t('theme.toggle')}
            title={t('theme.toggle')}
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}
