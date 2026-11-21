import { ExplorationEvent } from '../../core/api/api.types';

export interface EventKindInfo {
  label: string;
  glyph: string;
  thought: boolean;
  danger: boolean;
}

const KINDS: Record<string, { label: string; glyph: string }> = {
  thought: { label: 'Thought', glyph: '“' },
  begin: { label: 'Begin', glyph: '▶' },
  look: { label: 'Look', glyph: '◉' },
  sweep: { label: 'Sweep', glyph: '◐' },
  zoom: { label: 'Zoom', glyph: '⊕' },
  look_from: { label: 'Look from another panorama', glyph: '⇄' },
  confirm: { label: 'Confirm', glyph: '⌕' },
  mark_candidate: { label: 'Mark candidate', glyph: '◆' },
  mark_clear: { label: 'Mark clear', glyph: '✓' },
  mark_hidden: { label: 'Mark hidden', glyph: '▨' },
  answer_checklist: { label: 'Answer checklist', glyph: '☑' },
  find_other_scans: { label: 'Find other scans', glyph: '⟲' },
  show_map: { label: 'Show map', glyph: '▦' },
  note: { label: 'Note', glyph: '✎' },
  submit_found: { label: 'Submit found', glyph: '⚑' },
  harness_submit: { label: 'Submitted by the harness', glyph: '⚑' },
  tool_error: { label: 'Refused call', glyph: '⚠' },
};

export function eventKindInfo(kind: string, error: string | null = null): EventKindInfo {
  const known = KINDS[kind];
  return {
    label: known?.label ?? kind.replaceAll('_', ' '),
    glyph: known?.glyph ?? '?',
    thought: kind === 'thought',
    danger: kind === 'tool_error' || error !== null,
  };
}

export function argRows(request: unknown): { key: string; value: string }[] {
  if (request === null || typeof request !== 'object' || Array.isArray(request)) return [];
  return Object.entries(request as Record<string, unknown>)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([key, v]) => ({ key, value: typeof v === 'string' ? v : JSON.stringify(v) }));
}

export function timelineLine(event: ExplorationEvent): string {
  return event.summary.replace(/\s+/g, ' ').trim();
}

export function resultText(event: ExplorationEvent): string {
  const response = event.raw.response;
  if (response === null || response === undefined) return '';
  return typeof response === 'string' ? response : JSON.stringify(response, null, 2);
}

const CHECK_ORDER: Record<string, number> = { yes: 0, unsure: 1, no: 2 };

export function checklistRows(
  checklist: Record<string, string>,
): { feature: string; answer: string }[] {
  return Object.entries(checklist)
    .map(([feature, answer], i) => ({ feature, answer, i }))
    .sort((a, b) => (CHECK_ORDER[a.answer] ?? 3) - (CHECK_ORDER[b.answer] ?? 3) || a.i - b.i)
    .map(({ feature, answer }) => ({ feature, answer }));
}
