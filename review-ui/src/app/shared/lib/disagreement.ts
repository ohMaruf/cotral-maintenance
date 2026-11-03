import { CategoryKind } from '../../core/api/api.types';

export const LEVEL_DISAGREEMENT = 2;
export const PROBABILITY_DISAGREEMENT = 0.5;

/**
 * True when the models that gave a value spread by at least 2 levels
 * (or 0.5 for probabilities). Fewer than two values never disagree.
 */
export function modelsDisagree(
  values: readonly (number | undefined)[],
  kind: CategoryKind,
): boolean {
  const present = values.filter((v): v is number => v !== undefined && !Number.isNaN(v));
  if (present.length < 2) return false;
  const spread = Math.max(...present) - Math.min(...present);
  const threshold = kind === 'level' ? LEVEL_DISAGREEMENT : PROBABILITY_DISAGREEMENT;
  // Tolerate float noise such as 0.7 - 0.2 = 0.49999999999999994.
  return spread >= threshold - 1e-9;
}
