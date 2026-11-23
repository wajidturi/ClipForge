import {
  BarChart3,
  CalendarDays,
  Film,
  Gauge,
  Inbox,
  LibraryBig,
  Palette,
  Plus,
  Radio,
  Settings,
  Users,
  type LucideIcon,
} from 'lucide-react'

/** Sidebar entries. `phase` = roadmap phase that builds the page (placeholder until then). */
export type NavItem = { to: string; key: string; icon: LucideIcon; phase?: number }

export const NAV: NavItem[] = [
  { to: '/', key: 'dashboard', icon: Gauge },
  { to: '/create', key: 'create', icon: Plus },
  { to: '/shorts', key: 'library', icon: Film },
  { to: '/review', key: 'review', icon: Inbox },
  { to: '/sources', key: 'sources', icon: LibraryBig },
  { to: '/creators', key: 'creators', icon: Users, phase: 7 },
  { to: '/live', key: 'live', icon: Radio, phase: 7 },
  { to: '/schedule', key: 'schedule', icon: CalendarDays, phase: 9 },
  { to: '/brand', key: 'brand', icon: Palette, phase: 8 },
  { to: '/insights', key: 'insights', icon: BarChart3, phase: 9 },
  { to: '/settings', key: 'settings', icon: Settings },
]
