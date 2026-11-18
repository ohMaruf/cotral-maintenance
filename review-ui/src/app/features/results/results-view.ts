import { CategoryKind, ResultRow, RunInfo } from '../../core/api/api.types';

export type ScoreKey =
  | 'condition'
  | 'has_shelter'
  | 'shelter'
  | 'has_seating'
  | 'seating'
  | 'waiting_area'
  | 'accessibility'
  | 'has_lamp'
  | 'stop_visible';

export interface ScoreColumn {
  key: ScoreKey;
  label: string;
  kind: CategoryKind;
  /** The element this column rates; its cell says "missing" when the stop lacks it. */
  element?: 'shelter' | 'seating';
}

/** The scores of a result row, in display order. */
export const SCORE_COLUMNS: readonly ScoreColumn[] = [
  { key: 'condition', label: 'Condition', kind: 'condition' },
  { key: 'has_shelter', label: 'Shelter present', kind: 'probability' },
  { key: 'shelter', label: 'Shelter', kind: 'condition', element: 'shelter' },
  { key: 'has_seating', label: 'Seating present', kind: 'probability' },
  { key: 'seating', label: 'Seating', kind: 'condition', element: 'seating' },
  { key: 'waiting_area', label: 'Waiting area', kind: 'condition' },
  { key: 'accessibility', label: 'Access', kind: 'condition' },
  { key: 'has_lamp', label: 'Street lamp', kind: 'probability' },
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

/** The direction a column starts with: names, ranks and scores (0 is bad) upwards, worst first; moves furthest first. */
export function defaultDirection(key: SortKey): SortDirection {
  return key === 'distance' ? 'desc' : 'asc';
}

/** "shelter, seating": what the stop lacks; "none" when it lacks nothing, "–" until it is scored. */
export function missingText(missing: readonly string[] | null): string {
  if (missing === null) return '–';
  return missing.length ? missing.join(', ') : 'none';
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
