import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { Scene } from '@/lib/api/client'
import sceneJson from '@/test/scene.cinematic.json'
import { canvasProblem, DEFAULT_LIMITS, type CanvasValue } from './canvas'
import { CanvasPicker } from './CanvasPicker'
import { camTiles, designSize, dividerPoints, panels, viewCrop } from './draw'

const PRESETS = [
  { id: '9:16', label: 'Shorts', w: 1080, h: 1920 },
  { id: '4:5', label: 'Instagram feed', w: 1080, h: 1350 },
  { id: '1:1', label: 'Square', w: 1080, h: 1080 },
  { id: '16:9', label: 'YouTube', w: 1920, h: 1080 },
  { id: '4:3', label: 'Classic', w: 1440, h: 1080 },
]

const at = (template: string, canvas: CanvasValue) =>
  ({ ...(sceneJson as unknown as Scene), template, canvas }) as Scene

describe('video size geometry (like scene.py)', () => {
  it('keeps a 1080 short side for drawing', () => {
    expect(designSize(at('cinematic', { preset: '16:9', w: 1920, h: 1080 }))).toEqual([1920, 1080])
    expect(designSize(at('cinematic', { preset: 'custom', w: 720, h: 1280 }))).toEqual([1080, 1920])
  })

  it('puts stacked panels side by side on landscape', () => {
    const p = panels(at('streamer_first', { preset: '16:9', w: 1920, h: 1080 }))
    expect(p.cam!.x).toBeLessThan(p.game!.x)
    expect(p.cam!.y).toBe(p.game!.y)
    const tall = camTiles({ x: 0, y: 0, w: 600, h: 1000 }, 2)
    expect(tall[1]!.y).toBeGreaterThan(tall[0]!.y)
    const pts = dividerPoints(at('dual_vision', { preset: '16:9', w: 1920, h: 1080 }))
    expect(Math.min(...pts.map((q) => q[1]))).toBeLessThan(0)
  })

  it('frames a panel like a profile picture (like scene.view_crop)', () => {
    expect(viewCrop(1000, 500, { x: 0.25, y: 0.5, zoom: 2 }, 1920, 1080)).toEqual([
      230, 415, 500, 250,
    ])
    expect(viewCrop(1000, 500, { x: 0, y: 1, zoom: 1 }, 1920, 1080)).toEqual([0, 580, 1000, 500])
    expect(viewCrop(1000, 500, { x: 0.5, y: 0.5, zoom: 0.25 }, 1920, 1080).slice(2)).toEqual([
      1920, 960,
    ])
    expect(viewCrop(608, 1080, { x: 0.5, y: 0.5, zoom: 0.5 }, 1920, 1080, 1).slice(2)).toEqual([
      608, 1080,
    ])
    // the frames themselves never move
    const s = at('streamer_first', { preset: '9:16', w: 1080, h: 1920 })
    const framed = {
      ...s,
      regions: { ...s.regions, views: { game: { x: 0.2, y: 0.5, zoom: 2 } } },
    } as Scene
    expect(panels(framed)).toEqual(panels(s))
  })

  it('checks custom sizes like the backend', () => {
    expect(canvasProblem(720, 1280, DEFAULT_LIMITS)).toBeNull()
    expect(canvasProblem(100, 1280, DEFAULT_LIMITS)).toBe('range')
    expect(canvasProblem(3000, 500, DEFAULT_LIMITS)).toBe('ratio')
  })
})

function Harness({ seen }: { seen: CanvasValue[] }) {
  const [v, setV] = useState<CanvasValue>({ preset: '9:16', w: 1080, h: 1920 })
  return (
    <CanvasPicker
      value={v}
      presets={PRESETS}
      onChange={(c) => {
        seen.push(c)
        setV(c)
      }}
    />
  )
}

describe('size picker', () => {
  it('offers 5 presets and a custom size that updates as you type', async () => {
    const seen: CanvasValue[] = []
    render(<Harness seen={seen} />)
    expect(screen.getAllByRole('radio')).toHaveLength(6)
    await userEvent.click(screen.getByRole('radio', { name: /16:9/ }))
    expect(seen.at(-1)).toEqual({ preset: '16:9', w: 1920, h: 1080 })
    await userEvent.click(screen.getByRole('radio', { name: /custom/i }))
    const width = screen.getByLabelText('Width')
    await userEvent.clear(width)
    await userEvent.type(width, '1000')
    expect(seen.at(-1)).toEqual({ preset: 'custom', w: 1000, h: 1080 })
    await userEvent.clear(width)
    await userEvent.type(width, '9000')
    expect(screen.getByRole('status')).toHaveTextContent(/240 to 3840/)
    expect(seen.at(-1)!.w).not.toBe(9000) // an impossible size is not applied
    expect(width).toHaveValue(9000) // but what was typed stays visible
    await userEvent.click(screen.getByRole('button', { name: /swap/i }))
  })
})
