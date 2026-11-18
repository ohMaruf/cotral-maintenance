import { modelsDisagree } from './disagreement';

describe('modelsDisagree', () => {
  it('flags values that differ by 0.5 or more', () => {
    expect(modelsDisagree([0.2, 0.7])).toBe(true);
    expect(modelsDisagree([0, 1])).toBe(true);
    expect(modelsDisagree([0.75, 0.25])).toBe(true);
  });

  it('does not flag values that differ by less than 0.5', () => {
    expect(modelsDisagree([0.2, 0.69])).toBe(false);
    expect(modelsDisagree([0.5, 0.75])).toBe(false);
    expect(modelsDisagree([0.5, 0.5])).toBe(false);
  });

  it('never flags when fewer than two models have a value', () => {
    expect(modelsDisagree([undefined, 0.3])).toBe(false);
    expect(modelsDisagree([undefined, undefined])).toBe(false);
    expect(modelsDisagree([])).toBe(false);
  });
});
