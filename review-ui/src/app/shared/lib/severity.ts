import { CategoryKind } from '../../core/api/api.types';

/** The severity scale has this many steps above the best one: --sev-0 (good) .. --sev-4 (bad). */
export const SEVERITY_STEPS = 4;

/** Position of a value on its 0..1 scale, clamped. */
export function fraction(value: number): number {
  return Math.min(1, Math.max(0, value));
}

/**
 * CSS colour for a value. Conditions (0 bad .. 1 good) use the red -> green severity scale,
 * in buckets by rounding; probabilities are not a severity so they use a neutral accent.
 */
export function severityColor(value: number, kind: CategoryKind): string {
  if (kind === 'probability') return 'var(--prob)';
  const bucket = Math.round((1 - fraction(value)) * SEVERITY_STEPS);
  return `var(--sev-${bucket})`;
}
