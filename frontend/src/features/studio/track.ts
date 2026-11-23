/**
 * Port of backend `reframe.track_targets` / `_simplify` / `x_expression` so the live
 * preview follows the action exactly like the renderer's crop. Keep them in sync.
 */
export type Key = [number, number]

export function trackTargets(
  targets: [number, number | null][],
  cuts: number[],
  winW: number,
  deadZone = 0.06,
  maxSpeed = 0.35,
): Key[] {
  if (!targets.length) return [[0, (1 - winW) / 2]]
  const lo = 0
  const hi = Math.max(0, 1 - winW)
  const clamp = (centre: number) => Math.min(Math.max(centre - winW / 2, lo), hi)
  const first = targets.find(([, x]) => x != null)?.[1] ?? 0.5
  let left = clamp(first)
  const keys: Key[] = [[0, left]]
  let prevT = 0
  const sorted = [...cuts].sort((a, b) => a - b)
  for (const [t, tgt] of targets.slice(1)) {
    const crossed = sorted.some((c) => prevT < c && c <= t)
    if (tgt != null) {
      const want = clamp(tgt)
      if (crossed) left = want
      else if (Math.abs(left + winW / 2 - tgt) > deadZone) {
        const step = maxSpeed * (t - prevT)
        left = Math.min(Math.max(want, left - step), left + step)
      }
    }
    if (Math.abs(left - keys[keys.length - 1]![1]) > 1e-3 || crossed) keys.push([t, left])
    prevT = t
  }
  return simplify(keys)
}

function simplify(keys: Key[], tol = 0.004, limit = 80): Key[] {
  if (keys.length <= 2) return keys
  let out: Key[] = [keys[0]!]
  for (let i = 1; i < keys.length - 1; i++) {
    const [t0, x0] = out[out.length - 1]!
    const [t1, x1] = keys[i]!
    const [t2, x2] = keys[i + 1]!
    const interp = t2 > t0 ? x0 + ((x2 - x0) * (t1 - t0)) / (t2 - t0) : x1
    if (Math.abs(interp - x1) > tol) out.push(keys[i]!)
  }
  out.push(keys[keys.length - 1]!)
  while (out.length > limit) {
    const half = out.filter((_, i) => i % 2 === 0)
    const last = out[out.length - 1]!
    out = half[half.length - 1] === last ? half : [...half, last]
  }
  return out
}

/** Value of the piecewise-linear crop expression at time t (fraction of width). */
export function xAt(keys: Key[], t: number): number {
  if (keys.length === 1) return keys[0]![1]
  for (let i = 0; i < keys.length - 1; i++) {
    const [t0, x0] = keys[i]!
    const [t1, x1] = keys[i + 1]!
    if (t < t1) return t1 - t0 < 1e-6 ? x0 : x0 + ((x1 - x0) * (t - t0)) / (t1 - t0)
  }
  return keys[keys.length - 1]![1]
}

/** backend effects.zoom_expression */
export function zoomAt(peaks: number[], t: number, amount: number): number {
  if (!peaks.length) return 1
  const rise = 0.2
  const hold = 0.9
  const fall = 0.4
  const clip = (v: number) => Math.min(1, Math.max(0, v))
  let s = 0
  for (const p of peaks) s += clip((t - (p - rise)) / rise) * clip((p + hold + fall - t) / fall)
  return 1 + amount * Math.min(1, s)
}
