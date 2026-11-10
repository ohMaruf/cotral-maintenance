import { LatLon } from '../../core/api/api.types';

const EARTH_RADIUS_M = 6_371_000;
const RAD = Math.PI / 180;

/** Compass bearing in [0, 360). */
export function normalizeBearing(degrees: number): number {
  return ((degrees % 360) + 360) % 360;
}

/** Point reached from `from` after `distanceM` metres on a compass `bearing` (great circle). */
export function destination(from: LatLon, bearing: number, distanceM: number): LatLon {
  const lat1 = from[0] * RAD;
  const lon1 = from[1] * RAD;
  const brg = bearing * RAD;
  const d = distanceM / EARTH_RADIUS_M;
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(brg),
  );
  const lon2 =
    lon1 +
    Math.atan2(
      Math.sin(brg) * Math.sin(d) * Math.cos(lat1),
      Math.cos(d) - Math.sin(lat1) * Math.sin(lat2),
    );
  return [lat2 / RAD, ((((lon2 / RAD) % 360) + 540) % 360) - 180];
}

/** Distance in metres (haversine). */
export function distanceM(a: LatLon, b: LatLon): number {
  const dLat = (b[0] - a[0]) * RAD;
  const dLon = (b[1] - a[1]) * RAD;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * RAD) * Math.cos(b[0] * RAD) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

/**
 * Polygon of a camera's view: the apex at the camera, then an arc of radius
 * `radiusM` from heading - fov/2 to heading + fov/2. Not closed (Leaflet closes it).
 */
export function viewCone(
  origin: LatLon,
  heading: number,
  fov: number,
  radiusM: number,
  arcSteps = 8,
): LatLon[] {
  const half = fov / 2;
  const points: LatLon[] = [origin];
  for (let i = 0; i <= arcSteps; i++) {
    const bearing = heading - half + (fov * i) / arcSteps;
    points.push(destination(origin, normalizeBearing(bearing), radiusM));
  }
  return points;
}

/** Initial compass bearing from `a` to `b`, in [0, 360). */
export function bearingBetween(a: LatLon, b: LatLon): number {
  const dLon = (b[1] - a[1]) * RAD;
  const y = Math.sin(dLon) * Math.cos(b[0] * RAD);
  const x =
    Math.cos(a[0] * RAD) * Math.sin(b[0] * RAD) -
    Math.sin(a[0] * RAD) * Math.cos(b[0] * RAD) * Math.cos(dLon);
  return normalizeBearing(Math.atan2(y, x) / RAD);
}

export interface PathArrow {
  lat: number;
  lon: number;
  /** Direction of travel at this point. */
  bearing: number;
}

/**
 * Direction marks along a polyline: one every `spacingM` metres of path, the first half a
 * spacing in, at most `max` (the spacing grows to fit). Empty for fewer than two points.
 */
export function pathArrows(points: LatLon[], spacingM: number, max = 40): PathArrow[] {
  const lengths: number[] = [];
  let total = 0;
  for (let i = 1; i < points.length; i++) {
    const d = distanceM(points[i - 1], points[i]);
    lengths.push(d);
    total += d;
  }
  if (total === 0) return [];
  const step = Math.max(spacingM, total / max);
  const arrows: PathArrow[] = [];
  let next = step / 2;
  let walked = 0;
  for (let i = 0; i < lengths.length; i++) {
    while (next <= walked + lengths[i] && lengths[i] > 0) {
      const bearing = bearingBetween(points[i], points[i + 1]);
      const [lat, lon] = destination(points[i], bearing, next - walked);
      arrows.push({ lat, lon, bearing });
      next += step;
    }
    walked += lengths[i];
  }
  return arrows;
}
