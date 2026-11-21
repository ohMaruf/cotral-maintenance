import { LatLon, OsmFeature, ShapeStop, ShapeVerdictValue } from '../../core/api/api.types';
import { MapLayer } from '../../shared/geo-map/map-layers';
import { buildOsmFeatureLayers } from '../../shared/geo-map/osm-features';
import { distanceM } from '../../shared/lib/geo';

export const ROUTE_COLORS = ['#3d8bd9', '#e0a030', '#27b3a4', '#d96fa8', '#8fb83a', '#9a8cf0'];

function cssColor(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function routeColor(index: number): string {
  return ROUTE_COLORS[index % ROUTE_COLORS.length];
}

export interface LayerToggles {
  raw: boolean;
  snapped: boolean;
  features: boolean;
}

export const DEFAULT_TOGGLES: LayerToggles = { raw: true, snapped: true, features: true };

export const TOGGLE_LABELS: { key: keyof LayerToggles; label: string }[] = [
  { key: 'raw', label: 'Raw GTFS shapes' },
  { key: 'snapped', label: 'Snapped paths' },
  { key: 'features', label: 'OSM features' },
];

const TOGGLES_KEY = 'shapes.layers';

export function loadToggles(): LayerToggles {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(TOGGLES_KEY) ?? 'null');
    if (saved && typeof saved === 'object') {
      const o = saved as Record<string, unknown>;
      const pick = (k: keyof LayerToggles) =>
        typeof o[k] === 'boolean' ? (o[k] as boolean) : true;
      return { raw: pick('raw'), snapped: pick('snapped'), features: pick('features') };
    }
  } catch {
    return { ...DEFAULT_TOGGLES };
  }
  return { ...DEFAULT_TOGGLES };
}

export function saveToggles(toggles: LayerToggles): void {
  try {
    localStorage.setItem(TOGGLES_KEY, JSON.stringify(toggles));
  } catch {
    return;
  }
}

export function buildShapeLayers(
  stop: ShapeStop,
  toggles: LayerToggles = DEFAULT_TOGGLES,
): MapLayer[] {
  const layers: MapLayer[] = [];
  stop.routes.forEach((route, i) => {
    const color = routeColor(i);
    if (route.matched === null) {
      if (toggles.raw || toggles.snapped) {
        layers.push({
          type: 'polyline',
          id: `route-${route.shape}`,
          points: route.points,
          color,
          weight: 4,
          opacity: 0.9,
          tooltip: `shape ${route.shape} · ${route.trips} trips`,
        });
      }
    } else {
      if (toggles.raw) {
        layers.push({
          type: 'polyline',
          id: `route-${route.shape}`,
          points: route.points,
          color,
          weight: 2,
          opacity: 0.8,
          dashArray: '6 6',
          tooltip: `shape ${route.shape} · ${route.trips} trips`,
        });
      }
      if (toggles.snapped) {
        route.matched.forEach((piece, k) => {
          if (piece.length < 2) return;
          layers.push({
            type: 'polyline',
            id: `snapped-${route.shape}-${k}`,
            points: piece,
            color,
            weight: 4,
            opacity: 0.9,
            tooltip: `shape ${route.shape} · snapped to roads`,
          });
        });
      }
    }
    if (toggles.raw || toggles.snapped) {
      route.arrows.forEach((a, k) => {
        layers.push({
          type: 'marker',
          id: `arrow-${route.shape}-${k}`,
          lat: a.lat,
          lon: a.lon,
          text: '➤',
          className: 'arrow',
          color,
          rotateDeg: a.bearing - 90,
          size: 14,
        });
      });
    }
  });
  if (toggles.features) layers.push(...buildOsmFeatureLayers(stop.osm_features));
  for (const n of stop.neighbours) {
    layers.push({
      type: 'marker',
      id: `neighbour-${n.id}`,
      lat: n.lat,
      lon: n.lon,
      text: '',
      className: 'dot',
      size: 10,
      tooltip: `${n.id} ${n.name}`,
    });
  }
  layers.push({
    type: 'polyline',
    id: 'gtfs-to-verified',
    points: [stop.gtfs, stop.truth],
    color: cssColor('--pin-ring', 'white'),
    weight: 1.5,
    dashArray: '4 4',
  });
  const pin = (id: string, p: LatLon, text: string, kind: string, tooltip: string): MapLayer => ({
    type: 'marker',
    id,
    lat: p[0],
    lon: p[1],
    text,
    className: `pin-${kind}`,
    tooltip,
    zIndexOffset: 1000,
  });
  layers.push(pin('pin-gtfs', stop.gtfs, 'G', 'gtfs', `GTFS ${stop.id}`));
  if (stop.places) layers.push(pin('pin-places', stop.places, 'P', 'places', 'Places'));
  layers.push(pin('pin-verified', stop.truth, 'V', 'verified', 'Verified'));
  return layers;
}

export function shapeBounds(stop: ShapeStop): LatLon[] {
  const points = [stop.gtfs, stop.truth];
  if (stop.places) points.push(stop.places);
  return points;
}

export function distancesToVerified(stop: ShapeStop): { key: 'G' | 'P'; m: number }[] {
  const out: { key: 'G' | 'P'; m: number }[] = [
    { key: 'G', m: Math.round(distanceM(stop.gtfs, stop.truth)) },
  ];
  if (stop.places) out.push({ key: 'P', m: Math.round(distanceM(stop.places, stop.truth)) });
  return out;
}

export function streetViewUrl(p: LatLon): string {
  return `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${p[0]},${p[1]}`;
}

export function mapsSearchUrl(p: LatLon): string {
  return `https://www.google.com/maps/search/?api=1&query=${p[0]},${p[1]}`;
}

export function shortName(name: string): string {
  return name.replace(/ # .*/, '');
}

export const VERDICTS: { value: ShapeVerdictValue; key: string; label: string; short: string }[] = [
  { value: 'on_route', key: '1', label: 'On route', short: 'on route' },
  { value: 'off_route', key: '2', label: 'Off route', short: 'off route' },
  { value: 'unclear', key: '3', label: 'Unclear', short: 'unclear' },
];

export function verdictTone(v: ShapeVerdictValue): 'ok' | 'bad' | 'warn' {
  return v === 'on_route' ? 'ok' : v === 'off_route' ? 'bad' : 'warn';
}

const FLAG_ORDER = ['moved', 'left_of_path', 'far_from_path', 'on_detour'];

export function flagLabel(flag: string, minOffsetM: number): string {
  switch (flag) {
    case 'moved':
      return `Moved ≥ ${minOffsetM} m`;
    case 'left_of_path':
      return 'Left of path';
    case 'far_from_path':
      return 'Far from path';
    case 'on_detour':
      return 'On a detour';
    default:
      return flag;
  }
}

export function flagsPresent(stops: readonly ShapeStop[]): string[] {
  const present = new Set(stops.flatMap((s) => s.flags));
  const known = FLAG_ORDER.filter((f) => present.has(f));
  const unknown = [...present].filter((f) => !FLAG_ORDER.includes(f)).sort();
  return [...known, ...unknown];
}

export function filterByFlag(stops: readonly ShapeStop[], flag: string | null): ShapeStop[] {
  return flag === null ? [...stops] : stops.filter((s) => s.flags.includes(flag));
}

export function truthPathText(route: {
  truth_path_m: number | null;
  truth_path_side: string | null;
}): string {
  if (route.truth_path_m === null) return '–';
  return `${route.truth_path_m} m${route.truth_path_side ? ' ' + route.truth_path_side : ''}`;
}

export const FEATURE_RADIUS_M = 200;

export function nearbyFeatures(
  stop: ShapeStop,
): { feature: OsmFeature; m: number; text: string }[] {
  return stop.osm_features
    .map((feature) => ({
      feature,
      m: Math.round(distanceM([feature.lat, feature.lon], stop.truth)),
    }))
    .filter((x) => x.m <= FEATURE_RADIUS_M)
    .sort((a, b) => a.m - b.m)
    .map((x) => ({
      ...x,
      text: [x.feature.ref, x.feature.name].filter((p) => p !== '').join(' · '),
    }));
}
