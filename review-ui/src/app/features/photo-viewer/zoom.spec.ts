import { IDENTITY, MAX_SCALE, clampView, panBy, zoomAt } from './zoom';

const size = { w: 800, h: 600 };

describe('zoom', () => {
  it('keeps the point under the cursor fixed', () => {
    // Content point under (100, 50) before and after zooming 2x.
    const v = zoomAt(IDENTITY, 2, 100, 50, size);
    expect(v.scale).toBe(2);
    const contentBefore = { x: 100, y: 50 };
    const contentAfter = { x: (100 - v.x) / v.scale, y: (50 - v.y) / v.scale };
    expect(contentAfter.x).toBeCloseTo(contentBefore.x);
    expect(contentAfter.y).toBeCloseTo(contentBefore.y);
  });

  it('clamps the scale to 1..MAX and resets pan at scale 1', () => {
    expect(zoomAt(IDENTITY, 100, 0, 0, size).scale).toBe(MAX_SCALE);
    const zoomed = zoomAt(IDENTITY, 3, 200, 100, size);
    const out = zoomAt(zoomed, 0.01, 200, 100, size);
    expect(out).toEqual({ scale: 1, x: 0, y: 0 });
  });

  it('limits panning to the zoomed overflow', () => {
    const v = panBy({ scale: 2, x: 0, y: 0 }, 5000, -5000, size);
    expect(v.x).toBe(400);
    expect(v.y).toBe(-300);
    expect(clampView({ scale: 1, x: 50, y: 50 }, size)).toEqual({ scale: 1, x: 0, y: 0 });
  });
});
