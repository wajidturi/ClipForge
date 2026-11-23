/** Small, consistent form controls for the customisation studio panels. */
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function Section({
  title,
  children,
  action,
}: {
  title: string
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <section className="space-y-3 border-b border-border px-4 py-4 last:border-b-0">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[11px] font-semibold tracking-wider text-muted uppercase">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  )
}

export function Row({
  label,
  children,
  hint,
}: {
  label: string
  children: ReactNode
  hint?: string
}) {
  return (
    <div className="grid grid-cols-[6.5rem_1fr] items-center gap-2 text-xs">
      <span className="text-muted" title={hint}>
        {label}
      </span>
      <div className="flex min-w-0 items-center gap-2">{children}</div>
    </div>
  )
}

export function Slider({
  value,
  min,
  max,
  step = 1,
  onChange,
  onCommit,
  format,
  label,
}: {
  value: number
  min: number
  max: number
  step?: number
  onChange: (v: number) => void
  onCommit?: () => void
  format?: (v: number) => string
  label: string
}) {
  return (
    <>
      <input
        type="range"
        aria-label={label}
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        onPointerUp={onCommit}
        onKeyUp={onCommit}
        className="h-1.5 min-w-0 flex-1 cursor-pointer accent-accent"
      />
      <span className="w-12 text-right text-[11px] text-muted tabular-nums">
        {format ? format(value) : value}
      </span>
    </>
  )
}

export function ColorField({
  value,
  onChange,
  label,
}: {
  value: string
  onChange: (v: string) => void
  label: string
}) {
  const hex = value.slice(0, 7)
  return (
    <label className="flex items-center gap-2">
      <span
        className="relative size-7 overflow-hidden rounded-md border border-border"
        style={{ background: hex }}
      >
        <input
          type="color"
          aria-label={label}
          value={hex}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          className="absolute inset-0 cursor-pointer opacity-0"
        />
      </span>
      <span className="font-mono text-[11px] text-muted">{hex.toUpperCase()}</span>
    </label>
  )
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative h-5 w-9 shrink-0 rounded-full transition',
        checked ? 'bg-accent' : 'bg-border',
      )}
    >
      <span
        className={cn(
          'absolute top-0.5 size-4 rounded-full bg-white shadow transition-all',
          checked ? 'left-[1.125rem]' : 'left-0.5',
        )}
      />
    </button>
  )
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: { id: T; label: string }[]
  onChange: (v: T) => void
  label: string
}) {
  return (
    <div
      className="flex flex-wrap gap-1 rounded-lg bg-surface-2 p-0.5"
      role="radiogroup"
      aria-label={label}
    >
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={value === o.id}
          onClick={() => onChange(o.id)}
          className={cn(
            'rounded-md px-2 py-1 text-[11px] font-medium transition',
            value === o.id ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Select<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: { id: T; label: string }[]
  onChange: (v: T) => void
  label: string
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      className="h-8 min-w-0 flex-1 rounded-md border border-border bg-surface-2 px-2 text-xs"
    >
      {options.map((o) => (
        <option key={o.id} value={o.id}>
          {o.label}
        </option>
      ))}
    </select>
  )
}
