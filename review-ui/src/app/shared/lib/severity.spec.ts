import { fraction, severityColor } from './severity';

describe('severity', () => {
  it('maps levels to 0..1', () => {
    expect(fraction(0, 'level')).toBe(0);
    expect(fraction(2, 'level')).toBe(0.5);
    expect(fraction(4, 'level')).toBe(1);
  });

  it('keeps probabilities as they are and clamps out-of-range values', () => {
    expect(fraction(0.3, 'probability')).toBe(0.3);
    expect(fraction(7, 'level')).toBe(1);
    expect(fraction(-1, 'probability')).toBe(0);
  });

  it('buckets levels into the severity scale by rounding', () => {
    expect(severityColor(0, 'level')).toBe('var(--sev-0)');
    expect(severityColor(1.4, 'level')).toBe('var(--sev-1)');
    expect(severityColor(1.5, 'level')).toBe('var(--sev-2)');
    expect(severityColor(9, 'level')).toBe('var(--sev-4)');
  });

  it('uses a neutral colour for probabilities', () => {
    expect(severityColor(0.9, 'probability')).toBe('var(--prob)');
  });
});
