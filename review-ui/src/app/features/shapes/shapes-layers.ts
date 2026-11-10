import { LatLon, OsmFeature, ShapeStop, ShapeVerdictValue } from '../../core/api/api.types';
import { MapLayer } from '../../shared/geo-map/map-layers';
import { buildOsmFeatureLayers } from '../../shared/geo-map/osm-features';
import { distanceM } from '../../shared/lib/geo';

export const ROUTE_COLORS = ['#4285f4', '#a142f4', '#00acc1', '#f06292', '#7cb342', '#ff7043'];

export function routeColor(index: number): string {
  return ROUTE_COLORS[index % ROUTE_COLORS.length];
}

/** Which map layers are drawn. */
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

/** Saved toggles, defaulting anything missing or unreadable to on. */
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
    // storage unavailable or corrupt: use the defaults
  }
  return { ...DEFAULT_TOGGLES };
}

export function saveToggles(toggles: LayerToggles): void {
  try {
    localStorage.setItem(TOGGLES_KEY, JSON.stringify(toggles));
  } catch {
    // storage unavailable: the toggles just do not persist
  }
}

/**
 * Everything the shapes map draws for one stop, in z-order. Pure.
 *
 * With a snapped path, the raw GTFS shape is a thin dashed line and the snapped
 * path the main one; without, the raw shape is drawn solid (it is then the only
 * line, so it shows while either line toggle is on). Arrows come from the raw shape.
 */
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
    color: '#ffffff',
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

/** G, V and P when it exists. */
export function shapeBounds(stop: ShapeStop): LatLon[] {
  const points = [stop.gtfs, stop.truth];
  if (stop.places) points.push(stop.places);
  return points;
}

/** Distance in whole metres from each of G and P (when present) to V. */
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

/** The stop name without the trailing " # f1234" id the feed appends. */
export function shortName(name: string): string {
  return name.replace(/ # .*/, '');
}

export const VERDICTS: { value: ShapeVerdictValue; key: string; label: string; short: string }[] = [
  { value: 'on_route', key: '1', label: '1 · V on route', short: 'on route' },
  { value: 'off_route', key: '2', label: '2 · V off route', short: 'off route' },
  { value: 'unclear', key: '3', label: '3 · Unclear', short: 'unclear' },
];

export function verdictTone(v: ShapeVerdictValue): 'ok' | 'bad' | 'warn' {
  return v === 'on_route' ? 'ok' : v === 'off_route' ? 'bad' : 'warn';
}

const FLAG_ORDER = ['moved', 'left_of_path', 'far_from_path', 'on_detour'];

/** Human label of a flag; unknown flags are shown as-is. */
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

/** Flags present in the data: the known ones in contract order, then unknown ones alphabetically. */
export function flagsPresent(stops: readonly ShapeStop[]): string[] {
  const present = new Set(stops.flatMap((s) => s.flags));
  const known = FLAG_ORDER.filter((f) => present.has(f));
  const unknown = [...present].filter((f) => !FLAG_ORDER.includes(f)).sort();
  return [...known, ...unknown];
}

/** The stops carrying `flag`, in order; all of them when `flag` is null. */
export function filterByFlag(stops: readonly ShapeStop[], flag: string | null): ShapeStop[] {
  return flag === null ? [...stops] : stops.filter((s) => s.flags.includes(flag));
}

/** "4.2 m right"; "–" when the route has no snapped path. */
export function truthPathText(route: {
  truth_path_m: number | null;
  truth_path_side: string | null;
}): string {
  if (route.truth_path_m === null) return '–';
  return `${route.truth_path_m} m${route.truth_path_side ? ' ' + route.truth_path_side : ''}`;
}

export const FEATURE_RADIUS_M = 200;

/** OSM features within 200 m of V, nearest first, with whole-metre distances. */
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
