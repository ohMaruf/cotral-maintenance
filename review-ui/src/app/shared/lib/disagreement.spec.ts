import { modelsDisagree } from './disagreement';

describe('modelsDisagree', () => {
  it('flags levels that differ by 2 or more', () => {
    expect(modelsDisagree([1, 3], 'level')).toBe(true);
    expect(modelsDisagree([4, 0], 'level')).toBe(true);
    expect(modelsDisagree([1.5, 3.5], 'level')).toBe(true);
  });

  it('does not flag levels that differ by less than 2', () => {
    expect(modelsDisagree([2, 3], 'level')).toBe(false);
    expect(modelsDisagree([1.2, 2.9], 'level')).toBe(false);
    expect(modelsDisagree([2, 2], 'level')).toBe(false);
  });

  it('flags probabilities that differ by 0.5 or more', () => {
    expect(modelsDisagree([0.2, 0.7], 'probability')).toBe(true);
    expect(modelsDisagree([0, 1], 'probability')).toBe(true);
    expect(modelsDisagree([0.2, 0.69], 'probability')).toBe(false);
  });

  it('never flags when fewer than two models have a value', () => {
    expect(modelsDisagree([undefined, 3], 'level')).toBe(false);
    expect(modelsDisagree([undefined, undefined], 'level')).toBe(false);
    expect(modelsDisagree([], 'probability')).toBe(false);
  });
});
