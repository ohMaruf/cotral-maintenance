import { CategoryKind } from '../../core/api/api.types';

export const LEVEL_MAX = 4;

/** Position of a value on its scale, clamped to 0..1. */
export function fraction(value: number, kind: CategoryKind): number {
  const f = kind === 'level' ? value / LEVEL_MAX : value;
  return Math.min(1, Math.max(0, f));
}

/**
 * CSS colour for a value. Levels use the green -> red severity scale (buckets 0..4,
 * rounded); probabilities are not a severity so they use a neutral accent.
 */
export function severityColor(value: number, kind: CategoryKind): string {
  if (kind === 'probability') return 'var(--prob)';
  const bucket = Math.min(LEVEL_MAX, Math.max(0, Math.round(value)));
  return `var(--sev-${bucket})`;
}
