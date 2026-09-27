import { describe, expect, it } from 'vitest'
import { applyH, closestPair, frameIndexAt, type ShowcaseFrame, type ShowcaseTrack } from './model'

const track = (id: number, cls: string, g: [number, number] | null, zones: string[] = []): ShowcaseTrack => ({
  id,
  cls,
  conf: 0.9,
  bbox: [0, 0, 10, 10],
  g,
  speed: null,
  zones,
})

describe('frameIndexAt', () => {
  const frames: ShowcaseFrame[] = [0, 0.04, 0.08, 0.12].map((t) => ({ t, tracks: [] }))

  it('returns the last frame at or before t', () => {
    expect(frameIndexAt(frames, 0.05)).toBe(1)
    expect(frameIndexAt(frames, 0.08)).toBe(2)
  })

  it('clamps before the first and after the last frame', () => {
    expect(frameIndexAt(frames, -1)).toBe(0)
    expect(frameIndexAt(frames, 99)).toBe(3)
    expect(frameIndexAt([], 1)).toBe(0)
  })
})

describe('applyH', () => {
  it('applies a translation', () => {
    expect(applyH([1, 0, 5, 0, 1, -3, 0, 0], [10, 10])).toEqual([15, 7])
  })

  it('divides by the projective term', () => {
    const [x, y] = applyH([1, 0, 0, 0, 1, 0, 0.001, 0], [100, 50])
    expect(x).toBeCloseTo(100 / 1.1)
    expect(y).toBeCloseTo(50 / 1.1)
  })
})

describe('closestPair', () => {
  it('picks the nearest person-vehicle pair inside the rule zones', () => {
    const frame: ShowcaseFrame = {
      t: 0,
      tracks: [
        track(1, 'person', [0, 0], ['apron']),
        track(2, 'heavy_vehicle', [3, 4], ['apron']),
        track(3, 'forklift', [1, 0], []), // closer, but outside the zone
        track(4, 'person', null, ['apron']), // no ground point
      ],
    }
    const pair = closestPair(frame, ['apron'])
    expect(pair?.person.id).toBe(1)
    expect(pair?.vehicle.id).toBe(2)
    expect(pair?.distance).toBeCloseTo(5)
    expect(closestPair(frame, [])?.vehicle.id).toBe(3)
  })

  it('returns null without both classes', () => {
    expect(closestPair({ t: 0, tracks: [track(1, 'person', [0, 0])] }, [])).toBeNull()
  })
})
