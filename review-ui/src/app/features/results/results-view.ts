import { CategoryKind, ResultRow, RunInfo } from '../../core/api/api.types';

export type ScoreKey =
  | 'shelter'
  | 'seating'
  | 'signage'
  | 'lighting'
  | 'waiting_area'
  | 'accessibility'
  | 'requires_maintenance'
  | 'stop_visible';

export interface ScoreColumn {
  key: ScoreKey;
  label: string;
  kind: CategoryKind;
}

/** The scores of a result row, in display order. */
export const SCORE_COLUMNS: readonly ScoreColumn[] = [
  { key: 'requires_maintenance', label: 'Overall', kind: 'level' },
  { key: 'shelter', label: 'Shelter', kind: 'level' },
  { key: 'seating', label: 'Seating', kind: 'level' },
  { key: 'signage', label: 'Signage', kind: 'level' },
  { key: 'lighting', label: 'Lighting', kind: 'level' },
  { key: 'waiting_area', label: 'Waiting area', kind: 'level' },
  { key: 'accessibility', label: 'Access', kind: 'level' },
  { key: 'stop_visible', label: 'Visible', kind: 'probability' },
];

export type SortKey = 'rank' | 'name' | 'distance' | ScoreKey;
export type SortDirection = 'asc' | 'desc';
export type Show = 'all' | 'ranked' | 'review';

const SORT_KEYS: readonly SortKey[] = [
  'rank',
  'name',
  'distance',
  ...SCORE_COLUMNS.map((c) => c.key),
];

export function parseSort(raw: string | null | undefined): SortKey | null {
  return SORT_KEYS.find((k) => k === raw) ?? null;
}

export function parseShow(raw: string | null | undefined): Show {
  return raw === 'ranked' || raw === 'review' ? raw : 'all';
}

/** The direction a column starts with: names and ranks upwards, scores worst first. */
export function defaultDirection(key: SortKey): SortDirection {
  return key === 'rank' || key === 'name' ? 'asc' : 'desc';
}

export function filterRows(rows: readonly ResultRow[], show: Show, query: string): ResultRow[] {
  const q = query.trim().toLowerCase();
  return rows.filter(
    (r) =>
      (show === 'all' || (show === 'review') === r.needs_review) &&
      (!q || r.name.toLowerCase().includes(q) || r.stop_id.toLowerCase().includes(q)),
  );
}

function valueOf(row: ResultRow, key: SortKey): number | string | null {
  switch (key) {
    case 'rank':
      return row.rank;
    case 'name':
      return row.name.toLowerCase();
    case 'distance':
      return row.found_from_gtfs_m;
    default:
      return row[key];
  }
}

/**
 * Stable sort by a column. Rows without a value always come last, whatever the direction;
 * ties keep their incoming order (the run's own ranking).
 */
export function sortRows(
  rows: readonly ResultRow[],
  key: SortKey,
  direction: SortDirection,
): ResultRow[] {
  const sign = direction === 'asc' ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index, value: valueOf(row, key) }))
    .sort((a, b) => {
      if (a.value === null && b.value === null) return a.index - b.index;
      if (a.value === null) return 1;
      if (b.value === null) return -1;
      const order = a.value < b.value ? -1 : a.value > b.value ? 1 : 0;
      return sign * order || a.index - b.index;
    })
    .map((x) => x.row);
}

const STATUS_ORDER = ['found', 'not_found', 'no_imagery', 'error'];

/** "found 5 · not found 1": the run's explorations by status, known statuses first. */
export function exploredSummary(
  explored: RunInfo['explored'],
): { status: string; count: number }[] {
  const known = STATUS_ORDER.filter((s) => s in explored);
  const other = Object.keys(explored)
    .filter((s) => !STATUS_ORDER.includes(s))
    .sort();
  return [...known, ...other].map((status) => ({ status, count: explored[status] }));
}

/** "6 Static, 40 tiles": billed requests by API; "nothing billed" for none. */
export function billedSummary(billed: RunInfo['billed']): string {
  const parts = Object.entries(billed)
    .filter(([, n]) => n > 0)
    .map(([api, n]) => `${n} ${api === 'static' ? 'Static' : api === 'tiles' ? 'tiles' : api}`);
  return parts.length ? parts.join(', ') : 'nothing billed';
}
