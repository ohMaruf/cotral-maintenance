import {
  BudgetUnit,
  ExplorationPhoto,
  ExplorationSummary,
  Harness,
  Photo,
} from '../../core/api/api.types';

export type OutcomeTone = 'ok' | 'warn' | 'bad' | 'neutral';

const OUTCOMES: Record<string, { label: string; tone: OutcomeTone }> = {
  found: { label: 'Found', tone: 'ok' },
  not_found: { label: 'Not found', tone: 'warn' },
  no_imagery: { label: 'No imagery', tone: 'bad' },
  error: { label: 'Error', tone: 'bad' },
};

export function outcomeInfo(outcome: string): { label: string; tone: OutcomeTone } {
  return OUTCOMES[outcome] ?? { label: outcome.replaceAll('_', ' '), tone: 'neutral' };
}

export function formatMeters(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  return `${value >= 100 ? Math.round(value) : value.toFixed(1)} m`;
}

export function formatDuration(seconds: number | null): string | null {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return h > 0 ? `${h} h ${pad(m)} min` : `${m} min ${pad(s)} s`;
}

export function runDuration(startedAt: string | null, finishedAt: string | null): string | null {
  if (!startedAt || !finishedAt) return null;
  const ms = Date.parse(finishedAt) - Date.parse(startedAt);
  return Number.isNaN(ms) ? null : formatDuration(ms / 1000);
}

export function formatTimestamp(iso: string | null): string {
  if (!iso) return '–';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return `${new Date(t).toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

export function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? 'undefined';
  } catch {
    return String(value);
  }
}

export function budgetLabel(used: number, max: number, unit: BudgetUnit): string {
  return `${used}/${max} ${unit}`;
}

export function budgetDetail(run: ExplorationSummary): string {
  const main = budgetLabel(run.budget_used, run.budget_max, run.budget_unit);
  return run.budget_unit === 'photos'
    ? main
    : `${main}, ${run.zooms_used} zooms, ${run.confirms_used} confirmations`;
}

export function billedLabel(run: ExplorationSummary): string {
  return `${run.billed_static} Static, ${run.billed_tiles} tiles`;
}

export function tilesLabel(run: ExplorationSummary): string | null {
  return run.tiles_used === null || run.tiles_max === null
    ? null
    : `${run.tiles_used}/${run.tiles_max} tiles`;
}

const START_KINDS: Record<string, string> = {
  osm_ref: 'OSM by ref',
  osm_nearest: 'OSM nearest',
  places: 'Places',
  gtfs: 'GTFS',
};

export function startLabel(kind: string | null): string | null {
  return kind === null ? null : (START_KINDS[kind] ?? kind.replaceAll('_', ' '));
}

export const UNVERSIONED = 'unversioned';

export function versionLabel(version: string): string {
  return version === UNVERSIONED ? 'unversioned' : `v${version}`;
}

export function shortCommit(commit: string | null): string | null {
  return commit ? commit.slice(0, 7) : null;
}

export function modelsLabel(harness: Harness): string | null {
  const { explorer_model: e, confirmer_model: c } = harness;
  if (!e && !c) return null;
  if (e === c) return e;
  return [e && `explorer ${e}`, c && `confirmer ${c}`].filter(Boolean).join(', ');
}

export function towardLabel(photo: ExplorationPhoto, photos: ExplorationPhoto[] = []): string {
  switch (photo.toward) {
    case 'sweep_ahead':
      return 'sweep ahead-right';
    case 'sweep_behind':
      return 'sweep behind-right';
    case 'stop_photo':
      return 'stop photo';
    case 'look_from':
      return 'look from another panorama';
    case 'aimed':
      return 'opening, aimed at the start';
    case 'zoom': {
      if (photo.parent === null) return 'zoom';
      const parent = photos.find((p) => p.index === photo.parent);
      const factor = parent && photo.fov > 0 ? Math.round(parent.fov / photo.fov) : null;
      return `zoom${factor ? ` ×${factor}` : ''} of photo ${photo.parent}`;
    }
    default:
      return photo.toward;
  }
}

export function runLabel(run: ExplorationSummary): string {
  return `${run.stop_id} ${run.name}`;
}

export function toViewerPhoto(photo: ExplorationPhoto): Photo {
  return {
    view: `photo_${photo.index}`,
    description: `Photo ${photo.index}${photo.opening ? ' (opening)' : ''}`,
    url: photo.url,
    distance_m: null,
    heading: photo.heading,
    copyright: photo.copyright,
  };
}
