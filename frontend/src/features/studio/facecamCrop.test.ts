import { describe, expect, it } from 'vitest'
import { CAM_MAX_GROW, coverCrop, hideRects, matteCrop } from './draw'

describe('facecam crops like the renderer', () => {
  it('caps how far a narrow tile grows (scene.cover_crop max_grow)', () => {
    const box = [0.81, 0.6, 0.116, 0.212]
    const [, , w, h] = coverCrop(box, 0.67, 2560, 1440, CAM_MAX_GROW)
    expect(h).toBeLessThanOrEqual(0.212 * 1440 * CAM_MAX_GROW + 2)
    expect(Math.abs(w / h - 0.67)).toBeLessThan(0.02)
    expect(coverCrop(box, 1, 2560, 1440, 1.3)).toEqual(coverCrop(box, 1, 2560, 1440))
  })

  it('finds the overlay areas to blur in the gameplay', () => {
    const r = hideRects([[0.1, 0.6, 0.2, 0.3]], 1920, 1080)
    expect(r).toHaveLength(1)
    const [x, y, w, h] = r[0]!
    expect(x).toBeLessThan(0.1 * 1920)
    expect(y).toBeLessThan(0.6 * 1080)
    expect(w % 2).toBe(0)
    expect(h % 2).toBe(0)
  })

  it('maps a cam crop into the cut-out video like matte.matte_crop', () => {
    expect(matteCrop([960, 540, 480, 270], 1920, 1080, 1280, 720)).toEqual([640, 360, 320, 180])
    const [x, y, w, h] = matteCrop([1900, 1070, 400, 300], 1920, 1080, 1280, 720)
    expect(x + w).toBeLessThanOrEqual(1280)
    expect(y + h).toBeLessThanOrEqual(720)
  })
})
