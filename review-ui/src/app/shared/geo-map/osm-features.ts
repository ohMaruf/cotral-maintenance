import { OsmFeature } from '../../core/api/api.types';
import { MapLayer } from './map-layers';

export const FEATURE_KINDS: { kind: string; code: string; label: string }[] = [
  { kind: 'bus_stop', code: 'B', label: 'bus stop' },
  { kind: 'platform', code: 'L', label: 'platform' },
  { kind: 'stop_position', code: 'S', label: 'stop position' },
  { kind: 'shelter', code: 'H', label: 'shelter' },
  { kind: 'bus_station', code: 'T', label: 'bus station' },
];

export const OSM_LEGEND: { code: string; label: string }[] = [
  ...FEATURE_KINDS.map(({ code, label }) => ({ code, label })),
  { code: '?', label: 'other OSM kind' },
];

export function featureCode(kind: string): string {
  return FEATURE_KINDS.find((k) => k.kind === kind)?.code ?? '?';
}

export function featureTooltip(f: OsmFeature): string {
  return [f.kind, f.ref, f.name, f.operator, f.id].filter((part) => part !== '').join(' · ');
}

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

export function loadShowFeatures(key: string): boolean {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(key) ?? 'null');
    return typeof saved === 'boolean' ? saved : true;
  } catch {
    return true;
  }
}

export function saveShowFeatures(key: string, show: boolean): void {
  try {
    localStorage.setItem(key, JSON.stringify(show));
  } catch {
    return;
  }
}
