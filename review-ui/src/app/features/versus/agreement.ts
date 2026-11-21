import { ScoreMap } from '../../core/api/api.types';
export const OVERALL_CATEGORY = 'condition';

export type Side = 'left' | 'right';
export type Choice = Side | 'skip';

export type Agreement =
  | { kind: 'agrees' | 'disagrees'; left: number; right: number }
  | { kind: 'tie'; left: number; right: number }
  | { kind: 'no-pick' }
  | { kind: 'no-score' };
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
