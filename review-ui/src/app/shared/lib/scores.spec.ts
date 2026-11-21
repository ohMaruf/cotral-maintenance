import { CATALOG, stop } from '../../testing';
import { filterStops, isAbsent, meanScore, parseSort, serializeSort, sortStops } from './scores';

const models = CATALOG.models;
const a = stop('a', { name: 'Alpha', scores: { clef: { shelter: 1 }, gemma: { shelter: 3 } } });
const b = stop('b', { name: 'Beta', scores: { clef: { shelter: 4 } } });
const c = stop('c', { name: 'Gamma' });
const d = stop('d', { name: 'Delta', scores: { clef: { shelter: 0 }, gemma: { shelter: 0 } } });
const all = [a, b, c, d];
const ids = (stops: { stop_id: string }[]) => stops.map((s) => s.stop_id).join('');

describe('scores helpers', () => {
  it('averages over the models that scored', () => {
    expect(meanScore(a.scores, models, 'shelter')).toBe(2);
    expect(meanScore(b.scores, models, 'shelter')).toBe(4);
    expect(meanScore(c.scores, models, 'shelter')).toBeUndefined();
  });

  it('sorts by one model with missing values last in both directions', () => {
    const key = { category: 'shelter', model: 'gemma' };
    expect(ids(sortStops(all, key, 'desc', models))).toBe('adbc');
    expect(ids(sortStops(all, key, 'asc', models))).toBe('dabc');
  });

  it('sorts by the mean of models', () => {
    const key = { category: 'shelter', model: 'mean' };
    expect(ids(sortStops(all, key, 'desc', models))).toBe('badc');
    expect(ids(sortStops(all, key, 'asc', models))).toBe('dabc');
  });

  it('is stable for ties and does not mutate its input', () => {
    const input = [d, c, a];
    const out = sortStops(input, { category: 'shelter', model: 'clef' }, 'asc', models);
    expect(ids(out)).toBe('dac');
    expect(ids(input)).toBe('dca');
  });

  it('filters by name or id, case-insensitively', () => {
    expect(ids(filterStops(all, 'alp'))).toBe('a');
    expect(ids(filterStops(all, 'C'))).toBe('c');
    expect(ids(filterStops(all, '  '))).toBe('abcd');
    expect(filterStops(all, 'zzz')).toEqual([]);
  });

  it('round-trips and validates the sort param', () => {
    const key = { category: 'shelter', model: 'clef' };
    expect(parseSort(serializeSort(key), CATALOG.categories, models)).toEqual(key);
    expect(parseSort('shelter:mean', CATALOG.categories, models)).toEqual({
      category: 'shelter',
      model: 'mean',
    });
    expect(parseSort('nope:clef', CATALOG.categories, models)).toBeNull();
    expect(parseSort('shelter:nobody', CATALOG.categories, models)).toBeNull();
    expect(parseSort('shelter', CATALOG.categories, models)).toBeNull();
    expect(parseSort(undefined, CATALOG.categories, models)).toBeNull();
  });

  it('treats a presence probability below the threshold as missing', () => {
    expect(isAbsent(0.49)).toBe(true);
    expect(isAbsent(0.5)).toBe(false);
    expect(isAbsent(null)).toBe(false);
  });

  it('sorts a merged element with missing worst, and reads the old has_ sort keys', () => {
    const x = stop('x', { scores: { clef: { has_shelter: 0.1, shelter: 0.9 } } });
    const y = stop('y', { scores: { clef: { has_shelter: 0.9, shelter: 0.4 } } });
    const key = { category: 'shelter', model: 'clef' };
    expect(ids(sortStops([y, x], key, 'asc', models))).toBe('xy');
    expect(ids(sortStops([x, y], key, 'desc', models))).toBe('yx');
    const categories = [
      { key: 'shelter', label: 'Shelter', kind: 'condition' as const, description: '' },
    ];
    expect(parseSort('has_shelter:clef', categories, models)).toEqual(key);
  });
});
