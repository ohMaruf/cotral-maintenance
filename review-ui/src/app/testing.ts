import {
  Catalog,
  JudgmentResponse,
  NextPairResponse,
  Photo,
  Progress,
  StopDetail,
  StopSummary,
} from './core/api/api.types';

export const CATALOG: Catalog = {
  categories: [
    { key: 'shelter', label: 'Shelter', kind: 'level', description: 'Is there a shelter?' },
    { key: 'classifiable', label: 'Sign visible', kind: 'probability', description: 'Sign?' },
    {
      key: 'priority',
      label: 'Priority',
      kind: 'level',
      description: 'Needs maintenance?',
    },
  ],
  models: [
    { key: 'clef', label: 'Clef', description: 'Expected level' },
    { key: 'gemma', label: 'Gemma', description: 'Integer level' },
  ],
};

export function photo(stopId: string, n: number): Photo {
  return {
    view: `sweep_${n}`,
    description: `Photo ${n} of ${stopId}`,
    url: `/api/stops/${stopId}/photos/sweep_${n}_640x640.jpg`,
    distance_m: 24 * n,
    heading: 90 * n,
    copyright: '© Google',
  };
}

export function stop(id: string, overrides: Partial<StopDetail> = {}): StopDetail {
  return {
    stop_id: id,
    name: `Stop ${id}`,
    lat: 41.9,
    lon: 12.5,
    imagery_date: '2025-06',
    photos: [1, 2, 3, 4].map((n) => photo(id, n)),
    scores: {},
    evidence: {},
    ...overrides,
  };
}

export function progress(overrides: Partial<Progress> = {}): Progress {
  return { judged: 0, skipped: 0, remaining: 3, ...overrides };
}

function summary(id: string): StopSummary {
  const { stop_id, name, lat, lon, imagery_date, photos } = stop(id);
  return { stop_id, name, lat, lon, imagery_date, photos };
}

export function nextPair(left = 'a', right = 'b', p = progress()): NextPairResponse {
  return { pair: { left: summary(left), right: summary(right) }, progress: p };
}

export function judgmentResponse(
  left = 'a',
  right = 'b',
  winner: string | null = 'a',
): JudgmentResponse {
  return {
    judgment: {
      id: 'j1',
      created_at: '2026-01-01T00:00:00Z',
      left,
      right,
      winner,
      loser: winner === null ? null : winner === left ? right : left,
      rater: null,
      decision_ms: 1200,
    },
    left: stop(left, {
      scores: {
        clef: { shelter: 3.2, classifiable: 0.9, priority: 3.1 },
        gemma: { shelter: 3, classifiable: 1, priority: 3 },
      },
      evidence: { gemma: { shelter: 'The roof is broken.' } },
    }),
    right: stop(right, {
      scores: {
        clef: { shelter: 0.4, classifiable: 0.2, priority: 0.8 },
        gemma: { shelter: 0, classifiable: 0, priority: 1 },
      },
      evidence: {},
    }),
    progress: progress({ judged: 1, remaining: 2 }),
  };
}
