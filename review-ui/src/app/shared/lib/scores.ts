import { Category, Model, ScoreMap, StopDetail } from '../../core/api/api.types';

/** Sort column: one model, or the mean over the models that scored the stop. */
export interface SortKey {
  category: string;
  model: string | 'mean';
}

export type SortDirection = 'asc' | 'desc';

export function scoreOf(scores: ScoreMap, model: string, category: string): number | undefined {
  return scores[model]?.[category];
}

export function meanScore(
  scores: ScoreMap,
  models: readonly Model[],
  category: string,
): number | undefined {
  const values = models
    .map((m) => scoreOf(scores, m.key, category))
    .filter((v): v is number => v !== undefined);
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : undefined;
}

export function sortValue(
  stop: StopDetail,
  key: SortKey,
  models: readonly Model[],
): number | undefined {
  return key.model === 'mean'
    ? meanScore(stop.scores, models, key.category)
    : scoreOf(stop.scores, key.model, key.category);
}

/**
 * Stable sort by a score. Stops without a value always come last, whatever the
 * direction. Ties keep their incoming order.
 */
export function sortStops(
  stops: readonly StopDetail[],
  key: SortKey,
  direction: SortDirection,
  models: readonly Model[],
): StopDetail[] {
  const sign = direction === 'asc' ? 1 : -1;
  return stops
    .map((stop, index) => ({ stop, index, value: sortValue(stop, key, models) }))
    .sort((a, b) => {
      if (a.value === undefined && b.value === undefined) return a.index - b.index;
      if (a.value === undefined) return 1;
      if (b.value === undefined) return -1;
      return sign * (a.value - b.value) || a.index - b.index;
    })
    .map((x) => x.stop);
}

/** Case-insensitive substring match on stop name or id. */
export function filterStops(stops: readonly StopDetail[], query: string): StopDetail[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...stops];
  return stops.filter(
    (s) => s.name.toLowerCase().includes(q) || s.stop_id.toLowerCase().includes(q),
  );
}

/** URL form of a sort key: "shelter:clef" or "shelter:mean". */
export function serializeSort(key: SortKey): string {
  return `${key.category}:${key.model}`;
}

/** Parses a URL sort param; null unless it names a known category and model (or mean). */
export function parseSort(
  raw: string | null | undefined,
  categories: readonly Category[],
  models: readonly Model[],
): SortKey | null {
  if (!raw) return null;
  const [category, model] = raw.split(':');
  if (!category || !model) return null;
  if (!categories.some((c) => c.key === category)) return null;
  if (model !== 'mean' && !models.some((m) => m.key === model)) return null;
  return { category, model };
}
