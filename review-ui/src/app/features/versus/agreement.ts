import { ScoreMap } from '../../core/api/api.types';

/** The catalog category stops are ranked by: the scorer's computed condition, 0 (bad) .. 1 (good). */
export const OVERALL_CATEGORY = 'condition';

export type Side = 'left' | 'right';
export type Choice = Side | 'skip';

export type Agreement =
  | { kind: 'agrees' | 'disagrees'; left: number; right: number }
  | { kind: 'tie'; left: number; right: number }
  | { kind: 'no-pick' }
  | { kind: 'no-score' };

/**
 * Whether a model's overall condition ranks the stops the way the rater chose:
 * the stop picked as needing maintenance more has the lower condition.
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
  const worse: Side = left < right ? 'left' : 'right';
  return { kind: worse === choice ? 'agrees' : 'disagrees', left, right };
}
