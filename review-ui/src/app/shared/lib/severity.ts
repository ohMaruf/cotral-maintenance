import { CategoryKind } from '../../core/api/api.types';

export const SEVERITY_STEPS = 4;

export function fraction(value: number): number {
  return Math.min(1, Math.max(0, value));
}

export function severityColor(value: number, kind: CategoryKind): string {
  if (kind === 'probability') return 'var(--color-text-muted)';
  const bucket = Math.round((1 - fraction(value)) * SEVERITY_STEPS);
  return `var(--sev-${bucket})`;
}
