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
  title: string;
  kind: CategoryKind;
  element?: 'shelter' | 'seating';
}

export const SCORE_COLUMNS: readonly ScoreColumn[] = [
  { key: 'condition', label: 'Condition', title: 'Condition', kind: 'condition' },
  { key: 'has_shelter', label: 'Has shelter', title: 'Shelter present', kind: 'probability' },
  { key: 'shelter', label: 'Shelter', title: 'Shelter', kind: 'condition', element: 'shelter' },
  { key: 'has_seating', label: 'Has seat', title: 'Seating present', kind: 'probability' },
  { key: 'seating', label: 'Seating', title: 'Seating', kind: 'condition', element: 'seating' },
  { key: 'waiting_area', label: 'Waiting', title: 'Waiting area', kind: 'condition' },
  { key: 'accessibility', label: 'Access', title: 'Accessibility', kind: 'condition' },
  { key: 'has_lamp', label: 'Has lamp', title: 'Street lamp', kind: 'probability' },
  { key: 'stop_visible', label: 'Visible', title: 'Stop visible', kind: 'probability' },
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

export function defaultDirection(key: SortKey): SortDirection {
  return key === 'distance' ? 'desc' : 'asc';
}

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

export function exploredSummary(
  explored: RunInfo['explored'],
): { status: string; count: number }[] {
  const known = STATUS_ORDER.filter((s) => s in explored);
  const other = Object.keys(explored)
    .filter((s) => !STATUS_ORDER.includes(s))
    .sort();
  return [...known, ...other].map((status) => ({ status, count: explored[status] }));
}

export function billedSummary(billed: RunInfo['billed']): string {
  const parts = Object.entries(billed)
    .filter(([, n]) => n > 0)
    .map(([api, n]) => `${n} ${api === 'static' ? 'Static' : api === 'tiles' ? 'tiles' : api}`);
  return parts.length ? parts.join(', ') : 'nothing billed';
}
