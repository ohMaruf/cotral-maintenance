import { ScoreMap } from '../../core/api/api.types';

/** The catalog category that holds a model's overall "needs maintenance" verdict. */
export const OVERALL_CATEGORY = 'requires_maintenance';

export type Side = 'left' | 'right';
export type Choice = Side | 'skip';

export type Agreement =
  | { kind: 'agrees' | 'disagrees'; left: number; right: number }
  | { kind: 'tie'; left: number; right: number }
  | { kind: 'no-pick' }
  | { kind: 'no-score' };

/**
 * Whether a model's overall maintenance score ranks the stops the way the rater
 * chose: the stop with the higher score needs maintenance more.
 */
export function modelAgreement(
  leftScores: ScoreMap,
  rightScores: ScoreMap,
  model: string,
  choice: Choice,
): Agreement {
  const left = leftScores[model]?.[OVERALL_CATEGORY];
  const right = rightScores[model]?.[OVERALL_CATEGORY];
  if (left === undefined || right === undefined) return { kind: 'no-score' };
  if (choice === 'skip') return { kind: 'no-pick' };
  if (left === right) return { kind: 'tie', left, right };
  const higher: Side = left > right ? 'left' : 'right';
  return { kind: higher === choice ? 'agrees' : 'disagrees', left, right };
}
