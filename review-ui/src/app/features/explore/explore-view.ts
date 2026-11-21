import {
  Exploration,
  ExplorationEvent,
  ExplorationPhoto,
  ExplorationSummary,
} from '../../core/api/api.types';
import { UNVERSIONED } from '../../shared/lib/explore-format';

export function parseSeq(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isInteger(n) && n > 0 ? n : null;
}

export function orderedEvents(run: Exploration): ExplorationEvent[] {
  return [...run.event_list].sort((a, b) => a.seq - b.seq);
}

export function currentEvent(
  events: ExplorationEvent[],
  seq: number | null,
): ExplorationEvent | null {
  return events.find((e) => e.seq === seq) ?? events[0] ?? null;
}

export type EventStep = 'prev' | 'next' | 'first' | 'last';

export function stepSeq(
  events: ExplorationEvent[],
  current: ExplorationEvent | null,
  step: EventStep,
): number | null {
  if (events.length === 0) return null;
  const i = current ? events.indexOf(current) : 0;
  const target =
    step === 'first'
      ? 0
      : step === 'last'
        ? events.length - 1
        : Math.min(Math.max(i + (step === 'next' ? 1 : -1), 0), events.length - 1);
  return target === i ? null : events[target].seq;
}

export function eventOfPhoto(events: ExplorationEvent[], photo: number): ExplorationEvent | null {
  return events.find((e) => e.photos.includes(photo)) ?? null;
}

export function stepPhotoSeq(
  events: ExplorationEvent[],
  current: ExplorationEvent | null,
  direction: 'next' | 'previous',
): number | null {
  const i = current ? events.indexOf(current) : -1;
  const candidates =
    direction === 'next'
      ? events.slice(i + 1).find((e) => e.photos.length > 0)
      : events
          .slice(0, Math.max(i, 0))
          .reverse()
          .find((e) => e.photos.length > 0);
  return candidates?.seq ?? null;
}

export function photoByIndex(run: Exploration, index: number | null): ExplorationPhoto | null {
  return index === null ? null : (run.photo_list.find((p) => p.index === index) ?? null);
}

export function adjacentRun(
  runs: ExplorationSummary[],
  runId: string | null,
  delta: 1 | -1,
): ExplorationSummary | null {
  if (runs.length === 0) return null;
  const i = runs.findIndex((r) => r.run_id === runId);
  if (i < 0) return delta === 1 ? runs[0] : runs[runs.length - 1];
  return runs[i + delta] ?? null;
}

export function compareVersions(a: string, b: string): number {
  const parse = (v: string): number[] | null => {
    const parts = v.split('.').map((p) => (/^\d+$/.test(p) ? Number(p) : NaN));
    return v === UNVERSIONED || parts.some(Number.isNaN) ? null : parts;
  };
  const pa = parse(a);
  const pb = parse(b);
  if (!pa || !pb) return pa ? -1 : pb ? 1 : a.localeCompare(b);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pb[i] ?? 0) - (pa[i] ?? 0);
    if (d !== 0) return d;
  }
  return 0;
}

export interface RunGroup {
  version: string;
  runs: ExplorationSummary[];
  found: number;
}

export function groupRuns(runs: ExplorationSummary[]): RunGroup[] {
  const byVersion = new Map<string, ExplorationSummary[]>();
  for (const run of runs) {
    const list = byVersion.get(run.harness.version) ?? [];
    list.push(run);
    byVersion.set(run.harness.version, list);
  }
  return [...byVersion.entries()]
    .sort(([a], [b]) => compareVersions(a, b))
    .map(([version, list]) => ({
      version,
      runs: list,
      found: list.filter((r) => r.outcome === 'found').length,
    }));
}

export function visibleRuns(
  runs: ExplorationSummary[],
  harness: string | null,
): ExplorationSummary[] {
  return groupRuns(runs)
    .filter((g) => harness === null || g.version === harness)
    .flatMap((g) => g.runs);
}
