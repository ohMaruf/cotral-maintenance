import { ResultRow } from '../../core/api/api.types';
import { resultRow } from './results-testing';
import {
  billedSummary,
  defaultDirection,
  exploredSummary,
  filterRows,
  parseShow,
  parseSort,
  sortRows,
} from './results-view';

const rows: ResultRow[] = [
  resultRow('a', { rank: 1, name: 'Alpha', requires_maintenance: 4, found_from_gtfs_m: 30 }),
  resultRow('b', { rank: 2, name: 'beta', requires_maintenance: 2, found_from_gtfs_m: 80 }),
  resultRow('c', {
    rank: null,
    name: 'Gamma',
    needs_review: true,
    requires_maintenance: null,
    found_from_gtfs_m: null,
    status: 'not_found',
  }),
  resultRow('d', { rank: 3, name: 'Delta', requires_maintenance: 1, found_from_gtfs_m: null }),
];
const ids = (list: ResultRow[]) => list.map((r) => r.stop_id);

describe('results-view', () => {
  it('parses the URL params, ignoring unknown values', () => {
    expect(parseSort('shelter')).toBe('shelter');
    expect(parseSort('requires_maintenance')).toBe('requires_maintenance');
    expect(parseSort('nope')).toBeNull();
    expect(parseSort(undefined)).toBeNull();
    expect(parseShow('review')).toBe('review');
    expect(parseShow('ranked')).toBe('ranked');
    expect(parseShow('x')).toBe('all');
  });

  it('starts names and ranks upwards and scores worst first', () => {
    expect(defaultDirection('rank')).toBe('asc');
    expect(defaultDirection('name')).toBe('asc');
    expect(defaultDirection('lighting')).toBe('desc');
    expect(defaultDirection('distance')).toBe('desc');
  });

  it('filters by what needs review and by name or id', () => {
    expect(ids(filterRows(rows, 'all', ''))).toEqual(['a', 'b', 'c', 'd']);
    expect(ids(filterRows(rows, 'ranked', ''))).toEqual(['a', 'b', 'd']);
    expect(ids(filterRows(rows, 'review', ''))).toEqual(['c']);
    expect(ids(filterRows(rows, 'all', ' ALP '))).toEqual(['a']);
    expect(ids(filterRows(rows, 'ranked', 'c'))).toEqual([]);
    expect(ids(filterRows(rows, 'review', 'gam'))).toEqual(['c']);
  });

  it('sorts by a score in both directions with missing values last', () => {
    expect(ids(sortRows(rows, 'requires_maintenance', 'desc'))).toEqual(['a', 'b', 'd', 'c']);
    expect(ids(sortRows(rows, 'requires_maintenance', 'asc'))).toEqual(['d', 'b', 'a', 'c']);
    expect(ids(sortRows(rows, 'distance', 'asc'))).toEqual(['a', 'b', 'c', 'd']);
  });

  it('sorts by rank and by name, case-insensitively', () => {
    expect(ids(sortRows([...rows].reverse(), 'rank', 'asc'))).toEqual(['a', 'b', 'd', 'c']);
    expect(ids(sortRows(rows, 'name', 'asc'))).toEqual(['a', 'b', 'd', 'c']);
    expect(ids(sortRows(rows, 'name', 'desc'))).toEqual(['c', 'd', 'b', 'a']);
  });

  it('keeps the incoming order of ties', () => {
    const tied = [resultRow('x', { shelter: 2 }), resultRow('y', { shelter: 2 })];
    expect(ids(sortRows(tied, 'shelter', 'desc'))).toEqual(['x', 'y']);
    expect(ids(sortRows(tied, 'shelter', 'asc'))).toEqual(['x', 'y']);
  });

  it('summarises explorations and billing', () => {
    expect(exploredSummary({ weird: 1, error: 2, found: 5, not_found: 1 })).toEqual([
      { status: 'found', count: 5 },
      { status: 'not_found', count: 1 },
      { status: 'error', count: 2 },
      { status: 'weird', count: 1 },
    ]);
    expect(billedSummary({ static: 6, tiles: 40, places: 0 })).toBe('6 Static, 40 tiles');
    expect(billedSummary({ places: 3 })).toBe('3 places');
    expect(billedSummary({})).toBe('nothing billed');
  });
});
