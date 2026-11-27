/** Undo-able scene edits shared by the studio panels and the canvas. */
import type { Captions, Effects, FontInfo, Layer, Regions, Scene } from '@/lib/api/client'

export type Edit = {
  scene: Scene
  /** transient = live while dragging a slider; `commit` records it as one undo step */
  update: (fn: (s: Scene) => Scene, transient?: boolean) => void
  commit: () => void
  time: number
  duration: number
  selected: string | null
  select: (id: string | null) => void
  fonts: FontInfo[]
  presets: Record<string, Captions>
  /** facecam backgrounds (id, label) and whether this cut has a person cut-out */
  backgrounds: { id: string; label: string }[]
  /** video size presets and the limits for a custom size */
  canvases: { id: string; label: string; w: number; h: number }[]
  canvasLimits: { min: number; max: number; ratio: number }
  cutOut: boolean
}

export function setRegions(e: Edit, patch: Partial<Regions>, transient = false) {
  e.update((s) => ({ ...s, regions: { ...s.regions, ...patch } }), transient)
}
export function setFrame(e: Edit, patch: Partial<Regions['frame']>, transient = false) {
  e.update(
    (s) => ({ ...s, regions: { ...s.regions, frame: { ...s.regions.frame, ...patch } } }),
    transient,
  )
}
export function setCam(e: Edit, patch: Partial<Regions['cam']>, transient = false) {
  e.update(
    (s) => ({ ...s, regions: { ...s.regions, cam: { ...s.regions.cam, ...patch } } }),
    transient,
  )
}
export function setDivider(e: Edit, patch: Partial<Regions['divider']>, transient = false) {
  e.update(
    (s) => ({ ...s, regions: { ...s.regions, divider: { ...s.regions.divider, ...patch } } }),
    transient,
  )
}
export function setCaptions(e: Edit, patch: Partial<Captions>, transient = false) {
  e.update((s) => ({ ...s, captions: { ...s.captions, ...patch } }), transient)
}
export function setEffects(e: Edit, patch: Partial<Effects>, transient = false) {
  e.update((s) => ({ ...s, effects: { ...s.effects, ...patch } }), transient)
}
export function setLayer(e: Edit, id: string, patch: Partial<Layer>, transient = false) {
  e.update(
    (s) => ({ ...s, layers: s.layers.map((l) => (l.id === id ? { ...l, ...patch } : l)) }),
    transient,
  )
}
export function addLayer(e: Edit, layer: Layer) {
  e.update((s) => ({ ...s, layers: [...s.layers, layer] }))
  e.select(layer.id)
}
export function removeLayer(e: Edit, id: string) {
  e.update((s) => ({ ...s, layers: s.layers.filter((l) => l.id !== id) }))
  e.select(null)
}
