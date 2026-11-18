export const SCORE_DISAGREEMENT = 0.5;

/**
 * True when the models that gave a value spread by at least 0.5 on the 0..1 scale
 * (two levels of the scorer's five). Fewer than two values never disagree.
 */
export function modelsDisagree(values: readonly (number | undefined)[]): boolean {
  const present = values.filter((v): v is number => v !== undefined && !Number.isNaN(v));
  if (present.length < 2) return false;
  const spread = Math.max(...present) - Math.min(...present);
  // Tolerate float noise such as 0.7 - 0.2 = 0.49999999999999994.
  return spread >= SCORE_DISAGREEMENT - 1e-9;
}
