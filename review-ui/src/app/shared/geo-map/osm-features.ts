import { OsmFeature } from '../../core/api/api.types';
import { MapLayer } from './map-layers';

/** One-letter code per OSM feature kind. Kinds not known yet get "?". */
export const FEATURE_KINDS: { kind: string; code: string; label: string }[] = [
  { kind: 'bus_stop', code: 'B', label: 'bus stop' },
  { kind: 'platform', code: 'L', label: 'platform' },
  { kind: 'stop_position', code: 'S', label: 'stop position' },
  { kind: 'shelter', code: 'H', label: 'shelter' },
  { kind: 'bus_station', code: 'T', label: 'bus station' },
];

/** The legend of the OSM feature pins: every known kind, then "other". */
export const OSM_LEGEND: { code: string; label: string }[] = [
  ...FEATURE_KINDS.map(({ code, label }) => ({ code, label })),
  { code: '?', label: 'other OSM kind' },
];

export function featureCode(kind: string): string {
  return FEATURE_KINDS.find((k) => k.kind === kind)?.code ?? '?';
}

/** "kind · ref · name · operator · id", empty parts skipped. */
export function featureTooltip(f: OsmFeature): string {
  return [f.kind, f.ref, f.name, f.operator, f.id].filter((part) => part !== '').join(' · ');
}

/**
 * A small lettered pin per OSM feature, drawn below the position pins (negative
 * z-offset). Shared by the Explore and Shapes maps. Pure.
 */
export function buildOsmFeatureLayers(features: readonly OsmFeature[]): MapLayer[] {
  return features.map((f) => ({
    type: 'marker',
    id: `feature-${f.id}`,
    lat: f.lat,
    lon: f.lon,
    text: featureCode(f.kind),
    className: 'pin-feature',
    size: 16,
    zIndexOffset: -500,
    tooltip: featureTooltip(f),
  }));
}

/** Saved on/off state of the OSM feature layer under `key`; on when missing or unreadable. */
export function loadShowFeatures(key: string): boolean {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(key) ?? 'null');
    return typeof saved === 'boolean' ? saved : true;
  } catch {
    return true; // storage unavailable or corrupt: the default
  }
}

export function saveShowFeatures(key: string, show: boolean): void {
  try {
    localStorage.setItem(key, JSON.stringify(show));
  } catch {
    // storage unavailable: the choice just does not persist
  }
}
