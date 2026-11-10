import { LatLon } from '../../core/api/api.types';
import {
  bearingBetween,
  destination,
  distanceM,
  normalizeBearing,
  pathArrows,
  viewCone,
} from './geo';

const ROME: LatLon = [41.9, 12.5];

describe('geo', () => {
  it('normalizes bearings', () => {
    expect(normalizeBearing(-90)).toBe(270);
    expect(normalizeBearing(370)).toBe(10);
    expect(normalizeBearing(360)).toBe(0);
  });

  it('computes the distance between two points', () => {
    expect(distanceM(ROME, ROME)).toBe(0);
    // One degree of latitude is about 111.2 km.
    expect(distanceM([0, 0], [1, 0])).toBeCloseTo(111_195, -2);
  });

  it('moves north, east and back by the requested distance', () => {
    const north = destination(ROME, 0, 100);
    expect(north[0]).toBeGreaterThan(ROME[0]);
    expect(north[1]).toBeCloseTo(ROME[1], 8);
    const east = destination(ROME, 90, 100);
    expect(east[1]).toBeGreaterThan(ROME[1]);
    expect(east[0]).toBeCloseTo(ROME[0], 5);
    expect(distanceM(ROME, destination(ROME, 123, 250))).toBeCloseTo(250, 3);
  });

  it('wraps the longitude across the antimeridian', () => {
    const p = destination([0, 179.999], 90, 1000);
    expect(p[1]).toBeLessThan(-170);
  });

  describe('viewCone', () => {
    it('starts at the camera and spans heading +- fov/2 at the radius', () => {
      const cone = viewCone(ROME, 90, 110, 25, 4);
      expect(cone).toHaveLength(1 + 5);
      expect(cone[0]).toEqual(ROME);
      for (const p of cone.slice(1)) expect(distanceM(ROME, p)).toBeCloseTo(25, 2);
      const first = cone[1];
      const last = cone[5];
      // Heading 90 (east) with 110 deg fov: edges at 35 and 145 degrees.
      const midEast = destination(ROME, 35, 25);
      expect(first[0]).toBeCloseTo(midEast[0], 8);
      expect(first[1]).toBeCloseTo(midEast[1], 8);
      const lastExpected = destination(ROME, 145, 25);
      expect(last[0]).toBeCloseTo(lastExpected[0], 8);
      expect(last[1]).toBeCloseTo(lastExpected[1], 8);
    });

    it('is symmetric around the heading', () => {
      const cone = viewCone(ROME, 0, 90, 30, 2);
      const [left, mid, right] = cone.slice(1);
      expect(mid[1]).toBeCloseTo(ROME[1], 8);
      expect(ROME[1] - left[1]).toBeCloseTo(right[1] - ROME[1], 8);
    });

    it('handles headings that wrap past north', () => {
      const cone = viewCone(ROME, 350, 60, 25, 2);
      expect(cone[1][1]).toBeLessThan(ROME[1]); // 320 deg: north-west
      expect(cone[3][1]).toBeGreaterThan(ROME[1]); // 20 deg: north-east
    });
  });
});

describe('bearingBetween', () => {
  it('gives compass bearings', () => {
    expect(bearingBetween([0, 0], [1, 0])).toBeCloseTo(0, 5);
    expect(bearingBetween([0, 0], [0, 1])).toBeCloseTo(90, 5);
    expect(bearingBetween([0, 0], [-1, 0])).toBeCloseTo(180, 5);
    expect(bearingBetween([0, 0], [0, -1])).toBeCloseTo(270, 5);
  });
});

describe('pathArrows', () => {
  // ~111 m per 0.001° of latitude: a 222 m line going north, then 111 m east
  const path: [number, number][] = [
    [41.0, 12.0],
    [41.002, 12.0],
    [41.002, 12.00133],
  ];

  it('places an arrow every spacing, the first half a spacing in, with the local bearing', () => {
    const arrows = pathArrows(path, 100);
    expect(arrows.length).toBe(3);
    expect(arrows[0].bearing).toBeCloseTo(0, 3);
    expect(distanceM(path[0], [arrows[0].lat, arrows[0].lon])).toBeCloseTo(50, 0);
    expect(distanceM(path[0], [arrows[1].lat, arrows[1].lon])).toBeCloseTo(150, 0);
    expect(arrows[2].bearing).toBeGreaterThan(80);
    expect(arrows[2].bearing).toBeLessThan(100);
  });

  it('caps the number of arrows by widening the spacing', () => {
    expect(pathArrows(path, 1, 5).length).toBeLessThanOrEqual(6);
    expect(pathArrows(path, 1, 5).length).toBeGreaterThanOrEqual(5);
  });

  it('gives nothing for a degenerate path', () => {
    expect(pathArrows([], 50)).toEqual([]);
    expect(pathArrows([[41, 12]], 50)).toEqual([]);
    expect(
      pathArrows(
        [
          [41, 12],
          [41, 12],
        ],
        50,
      ),
    ).toEqual([]);
  });
});
