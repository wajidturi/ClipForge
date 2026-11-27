/** Video size helpers shared by the size picker, the studio and the Create page. */
import type { Canvas } from '@/lib/api/client'

export type CanvasPreset = { id: string; label: string; w: number; h: number }
export type CanvasValue = { preset: NonNullable<Canvas['preset']>; w: number; h: number }
export type CanvasLimits = { min: number; max: number; ratio: number }

export const DEFAULT_LIMITS: CanvasLimits = { min: 240, max: 3840, ratio: 4 }

/** A scene's canvas with the defaults filled in (older scenes have none: 9:16). */
export function canvasOf(c: Canvas | null | undefined): CanvasValue {
  return { preset: c?.preset ?? '9:16', w: c?.w ?? 1080, h: c?.h ?? 1920 }
}

/** Same rule as the backend (scene.Canvas): why a size cannot be used, or null. */
export function canvasProblem(w: number, h: number, lim: CanvasLimits): string | null {
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return 'number'
  if (w < lim.min || h < lim.min || w > lim.max || h > lim.max) return 'range'
  if (Math.max(w, h) > lim.ratio * Math.min(w, h)) return 'ratio'
  return null
}

export function limitsOf(x: Record<string, number> | undefined): CanvasLimits {
  return x && x.min && x.max && x.ratio
    ? { min: x.min, max: x.max, ratio: x.ratio }
    : DEFAULT_LIMITS
}
