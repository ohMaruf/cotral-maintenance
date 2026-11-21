import {
  Exploration,
  ExplorationCandidate,
  ExplorationPhoto,
  LatLon,
  PositionKind,
} from '../../core/api/api.types';
import { pathArrows, viewCone } from '../../shared/lib/geo';
import { formatMeters } from '../../shared/lib/explore-format';
import { MapLayer, toLatLon } from '../../shared/geo-map/map-layers';
import { buildOsmFeatureLayers } from '../../shared/geo-map/osm-features';

export const CONE_RADIUS_M = 25;
const ARROW_SPACING_M = 60;

function themeColor(name: string): string {
  if (typeof document === 'undefined') return 'currentColor';
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || 'currentColor';
}

export const CANDIDATE_STATUSES = [
  'spotted',
  'awaiting_checklist',
  'confirmed',
  'rejected',
] as const;

export const PIN_LETTERS: Record<PositionKind, string> = {
  gtfs: 'G',
  places: 'P',
  verified: 'V',
  estimate: 'E',
};

export interface ExploreMapState {
  photosUsed: number;
  currentPhotos: number[];
  showOsmFeatures?: boolean;
}

export function photoLayerId(index: number): string {
  return `photo-${index}`;
}
export function photoIndexOfLayer(id: string): number | null {
  const m = /^photo-(\d+)$/.exec(id);
  return m ? Number(m[1]) : null;
}

function photoPoint(p: ExplorationPhoto): LatLon {
  return [p.lat, p.lon];
}

function photoTooltip(p: ExplorationPhoto): string {
  return `Photo ${p.index}${p.opening ? ' (opening)' : ''} · ${p.toward} · heading ${Math.round(p.heading)}°`;
}

export function candidateTooltip(c: ExplorationCandidate): string {
  const parts = [`Candidate ${c.index}`, c.kind, c.status.replaceAll('_', ' ')];
  if (c.evidence) parts.push(`evidence: ${c.evidence.replaceAll('_', ' ')}`);
  parts.push(`basis: ${c.basis.replaceAll('_', ' ')}`);
  return parts.join(' · ');
}
export function buildExploreLayers(run: Exploration, state: ExploreMapState): MapLayer[] {
  const layers: MapLayer[] = [];
  const pathColor = themeColor('--color-accent');
  const currentColor = themeColor('--pin-current');
  const coneColor = themeColor('--color-border-strong');
  const photos = [...run.photo_list].sort((a, b) => a.index - b.index);
  const taken = photos.filter((p) => p.index <= state.photosUsed);
  const later = photos.filter((p) => p.index > state.photosUsed);
  if (run.path.length > 1) {
    layers.push({
      type: 'polyline',
      id: 'path',
      points: run.path,
      color: pathColor,
      weight: 4,
      opacity: 0.8,
      tooltip: 'The bus path (direction of travel →)',
    });
    pathArrows(run.path, ARROW_SPACING_M).forEach((a, k) => {
      layers.push({
        type: 'marker',
        id: `path-arrow-${k}`,
        lat: a.lat,
        lon: a.lon,
        text: '➤',
        className: 'arrow',
        color: pathColor,
        rotateDeg: a.bearing - 90,
        size: 14,
      });
    });
  }
  const cone = (p: ExplorationPhoto): MapLayer => {
    const current = state.currentPhotos.includes(p.index);
    const future = p.index > state.photosUsed;
    return {
      type: 'polygon',
      id: `cone-${p.index}`,
      points: viewCone(photoPoint(p), p.heading, p.fov, CONE_RADIUS_M),
      color: current ? currentColor : coneColor,
      weight: current ? 2 : 1,
      opacity: current ? 1 : future ? 0.3 : 0.6,
      fillOpacity: current ? 0.35 : future ? 0.02 : 0.08,
    };
  };
  const isCurrent = (p: ExplorationPhoto) => state.currentPhotos.includes(p.index);
  for (const p of [...later, ...taken].filter((p) => !isCurrent(p))) layers.push(cone(p));
  for (const p of photos.filter(isCurrent)) layers.push(cone(p));
  if (state.showOsmFeatures ?? true) layers.push(...buildOsmFeatureLayers(run.osm_features));

  for (const pos of run.positions) {
    layers.push({
      type: 'marker',
      id: `pos-${pos.kind}`,
      lat: pos.lat,
      lon: pos.lon,
      text: PIN_LETTERS[pos.kind] ?? '?',
      className: `pin-${pos.kind}`,
      tooltip: `${pos.label}${pos.error_m === null ? '' : ` · ${formatMeters(pos.error_m)} from verified`}`,
    });
  }

  for (const c of run.candidates) {
    layers.push({
      type: 'marker',
      id: `candidate-${c.index}`,
      lat: c.lat,
      lon: c.lon,
      text: String(c.index),
      className: `diamond cand-${c.status}`,
      size: 24,
      tooltip: candidateTooltip(c),
    });
  }

  for (const p of photos) {
    const current = isCurrent(p);
    const future = p.index > state.photosUsed;
    layers.push({
      type: 'marker',
      id: photoLayerId(p.index),
      lat: p.lat,
      lon: p.lon,
      text: String(p.index),
      className: `camera ${current ? 'current' : future ? 'future' : 'past'}`,
      tooltip: photoTooltip(p),
      interactive: true,
      zIndexOffset: current ? 1000 : 0,
    });
  }
  return layers;
}
export function exploreBounds(run: Exploration): LatLon[] {
  return [
    ...run.positions.map(toLatLon),
    ...run.photo_list.map(photoPoint),
    ...run.candidates.map(toLatLon),
  ];
}
