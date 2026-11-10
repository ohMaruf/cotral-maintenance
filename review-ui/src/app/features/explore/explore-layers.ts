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
const PATH_COLOR = '#26c6da';
const CURRENT_COLOR = '#ff6d00';

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
  /** Photos taken so far (`photos_used` of the current event); later ones are faded. */
  photosUsed: number;
  /** Photos taken by the current event, highlighted. */
  currentPhotos: number[];
  /** Draw the OSM feature pins; on when omitted. */
  showOsmFeatures?: boolean;
}

export function photoLayerId(index: number): string {
  return `photo-${index}`;
}

/** Inverse of photoLayerId; null for any other layer id. */
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

/** Everything the explore map draws, in z-order. Pure. */
export function buildExploreLayers(run: Exploration, state: ExploreMapState): MapLayer[] {
  const layers: MapLayer[] = [];
  const photos = [...run.photo_list].sort((a, b) => a.index - b.index);
  const taken = photos.filter((p) => p.index <= state.photosUsed);
  const later = photos.filter((p) => p.index > state.photosUsed);

  // The bus's path with direction-of-travel arrows, below everything else.
  if (run.path.length > 1) {
    layers.push({
      type: 'polyline',
      id: 'path',
      points: run.path,
      color: PATH_COLOR,
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
        color: PATH_COLOR,
        rotateDeg: a.bearing - 90,
        size: 14,
      });
    });
  }

  // View cones: later photos first so earlier ones sit on top, current last.
  const cone = (p: ExplorationPhoto): MapLayer => {
    const current = state.currentPhotos.includes(p.index);
    const future = p.index > state.photosUsed;
    return {
      type: 'polygon',
      id: `cone-${p.index}`,
      points: viewCone(photoPoint(p), p.heading, p.fov, CONE_RADIUS_M),
      color: current ? CURRENT_COLOR : '#ffeb3b',
      weight: current ? 2 : 1,
      opacity: future ? 0.3 : 0.9,
      fillOpacity: current ? 0.4 : future ? 0.05 : 0.18,
    };
  };
  const isCurrent = (p: ExplorationPhoto) => state.currentPhotos.includes(p.index);
  for (const p of [...later, ...taken].filter((p) => !isCurrent(p))) layers.push(cone(p));
  for (const p of photos.filter(isCurrent)) layers.push(cone(p));

  // OSM features sit below the position pins (negative z-offset) and the photos.
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

/** Every position, photo and candidate location: the view to fit for a run (not the whole path). */
export function exploreBounds(run: Exploration): LatLon[] {
  return [
    ...run.positions.map(toLatLon),
    ...run.photo_list.map(photoPoint),
    ...run.candidates.map(toLatLon),
  ];
}
