import { ExplorationEvent } from '../../core/api/api.types';

export type KindIcon =
  | 'message'
  | 'play'
  | 'eye'
  | 'sweep'
  | 'zoom'
  | 'swap'
  | 'confirm'
  | 'pin'
  | 'check'
  | 'hidden'
  | 'checklist'
  | 'layers'
  | 'map'
  | 'note'
  | 'send'
  | 'alert'
  | 'unknown';

export interface EventKindInfo {
  label: string;
  icon: KindIcon;
  thought: boolean;
  danger: boolean;
}

const KINDS: Record<string, { label: string; icon: KindIcon }> = {
  thought: { label: 'Thought', icon: 'message' },
  begin: { label: 'Begin', icon: 'play' },
  look: { label: 'Look', icon: 'eye' },
  sweep: { label: 'Sweep', icon: 'sweep' },
  zoom: { label: 'Zoom', icon: 'zoom' },
  look_from: { label: 'Look from another panorama', icon: 'swap' },
  confirm: { label: 'Confirm', icon: 'confirm' },
  mark_candidate: { label: 'Mark candidate', icon: 'pin' },
  mark_clear: { label: 'Mark clear', icon: 'check' },
  mark_hidden: { label: 'Mark hidden', icon: 'hidden' },
  answer_checklist: { label: 'Answer checklist', icon: 'checklist' },
  find_other_scans: { label: 'Find other scans', icon: 'layers' },
  show_map: { label: 'Show map', icon: 'map' },
  note: { label: 'Note', icon: 'note' },
  submit_found: { label: 'Submit found', icon: 'send' },
  harness_submit: { label: 'Submitted by the harness', icon: 'send' },
  tool_error: { label: 'Refused call', icon: 'alert' },
};

export function eventKindInfo(kind: string, error: string | null = null): EventKindInfo {
  const known = KINDS[kind];
  return {
    label: known?.label ?? kind.replaceAll('_', ' '),
    icon: known?.icon ?? 'unknown',
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
