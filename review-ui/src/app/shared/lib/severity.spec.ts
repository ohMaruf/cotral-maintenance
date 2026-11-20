import { fraction, severityColor } from './severity';

describe('severity', () => {
  it('keeps values on 0..1 and clamps the ones outside', () => {
    expect(fraction(0)).toBe(0);
    expect(fraction(0.3)).toBe(0.3);
    expect(fraction(1)).toBe(1);
    expect(fraction(7)).toBe(1);
    expect(fraction(-1)).toBe(0);
  });

  it('buckets conditions into the severity scale, good as green and bad as red', () => {
    expect(severityColor(1, 'condition')).toBe('var(--sev-0)');
    expect(severityColor(0.9, 'condition')).toBe('var(--sev-0)');
    expect(severityColor(0.7, 'condition')).toBe('var(--sev-1)');
    expect(severityColor(0.5, 'condition')).toBe('var(--sev-2)');
    expect(severityColor(0.3, 'condition')).toBe('var(--sev-3)');
    expect(severityColor(0, 'condition')).toBe('var(--sev-4)');
    expect(severityColor(-3, 'condition')).toBe('var(--sev-4)');
  });

  it('uses a neutral colour for probabilities', () => {
    expect(severityColor(0.9, 'probability')).toBe('var(--color-text-muted)');
    expect(severityColor(0.1, 'probability')).toBe('var(--color-text-muted)');
  });
});
