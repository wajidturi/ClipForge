import { describe, expect, it } from 'vitest'
import { camList, camTiles, TILE_GAP } from './draw'

describe('facecam panel with several people', () => {
  it('splits the panel like the renderer (scene.cam_tiles)', () => {
    const r = { x: 14, y: 14, w: 1052, h: 782 }
    expect(camTiles(r, 1)).toEqual([r])
    expect(camTiles(r, 0)).toEqual([])
    const tiles = camTiles(r, 2)
    expect(tiles).toHaveLength(2)
    expect(tiles[0]!.x).toBe(14)
    expect(tiles[1]!.x - (tiles[0]!.x + tiles[0]!.w)).toBe(TILE_GAP)
    expect(tiles[1]!.x + tiles[1]!.w).toBe(r.x + r.w)
  })

  it('shows everyone stacked, the main person in the bubble', () => {
    const cut = {
      cam: [0.8, 0.7, 0.1, 0.2],
      cams: [
        [0.1, 0.7, 0.1, 0.2],
        [0.8, 0.7, 0.1, 0.2],
      ],
      primary: 1,
    }
    expect(camList(cut, 'streamer_first')).toHaveLength(2)
    expect(camList(cut, 'floating_facecam')).toEqual([[0.8, 0.7, 0.1, 0.2]])
    expect(camList({ cam: [0.8, 0.7, 0.1, 0.2] }, 'dual_vision')).toEqual([[0.8, 0.7, 0.1, 0.2]])
    expect(camList({ cam: null, cams: [] }, 'dual_vision')).toEqual([])
  })
})
