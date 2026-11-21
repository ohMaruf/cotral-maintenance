export const SCORE_DISAGREEMENT = 0.5;

export function modelsDisagree(values: readonly (number | undefined)[]): boolean {
  const present = values.filter((v): v is number => v !== undefined && !Number.isNaN(v));
  if (present.length < 2) return false;
  const spread = Math.max(...present) - Math.min(...present);

  return spread >= SCORE_DISAGREEMENT - 1e-9;
}

export interface ElementReading {
  absent: boolean;
  value: number | undefined;
}

export function elementsDisagree(readings: readonly ElementReading[]): boolean {
  if (new Set(readings.map((r) => r.absent)).size > 1) return true;
  return modelsDisagree(readings.filter((r) => !r.absent).map((r) => r.value));
}
