import {
  Exploration,
  ExplorationCandidate,
  ExplorationEvent,
  ExplorationPhoto,
  ExplorationSummary,
  Harness,
} from '../../core/api/api.types';

export function photo(index: number, overrides: Partial<ExplorationPhoto> = {}): ExplorationPhoto {
  return {
    index,
    url: `/api/explorations/f1/photos/p${index}.jpg`,
    pano_id: `pano${index}`,
    lat: 41.9 + index * 0.0002,
    lon: 12.5 + index * 0.0001,
    date: '2025-06',
    heading: 90 + index * 10,
    fov: 100,
    pitch: 0,
    along_m: index * 8,
    right_m: 2,
    toward: 'forward',
    opening: index <= 2,
    copyright: '© Google',
    billed: null,
    width: null,
    height: null,
    shot: 0,
    parent: null,
    source: 'static',
    tiles: 0,
    ...overrides,
  };
}

export function event(seq: number, overrides: Partial<ExplorationEvent> = {}): ExplorationEvent {
  return {
    seq,
    kind: 'note',
    summary: `Event ${seq}`,
    error: null,
    photos: [],
    photos_used: 0,
    budget_used: 0,
    raw: { request: { text: `q${seq}` }, response: `a${seq}` },
    ...overrides,
  };
}

export function candidate(
  index: number,
  overrides: Partial<ExplorationCandidate> = {},
): ExplorationCandidate {
  return {
    index,
    kind: 'sign',
    lat: 41.9003,
    lon: 12.5002,
    along_m: 12,
    right_m: 3,
    status: 'confirmed',
    evidence: 'cotral_sign',
    basis: 'triangulated',
    checklist: { cotral_logo: 'yes', plate: 'unsure', shelter: 'no', timetable: 'no' },
    confirmer_note: '',
    confirm_photo: null,
    ...overrides,
  };
}

export const UNVERSIONED_HARNESS: Harness = {
  version: 'unversioned',
  git_commit: null,
  git_dirty: null,
  prompt_sha256: null,
  explorer_model: null,
  confirmer_model: null,
};

/** The harness block of a 0.6 run. */
export function harness(version = '0.6.0', overrides: Partial<Harness> = {}): Harness {
  return {
    version,
    git_commit: 'da028ea9b1837bcd18058fb5234c96e1dbb51146',
    git_dirty: true,
    prompt_sha256: 'ab'.repeat(32),
    explorer_model: 'haiku',
    confirmer_model: 'haiku',
    ...overrides,
  };
}

export function summary(
  runId: string,
  overrides: Partial<ExplorationSummary> = {},
): ExplorationSummary {
  return {
    run_id: runId,
    stop_id: runId,
    name: `Stop ${runId}`,
    outcome: 'found',
    outcome_reason: null,
    model: 'claude-haiku-5-5',
    photos: 3,
    max_photos: 14,
    budget_unit: 'photos',
    budget_used: 3,
    budget_max: 14,
    zooms_used: 0,
    confirms_used: 0,
    billed_used: null,
    stop_photos_used: 0,
    harness: { ...UNVERSIONED_HARNESS },
    billed_static: null,
    billed_tiles: null,
    tiles_used: null,
    tiles_max: null,
    start_kind: null,
    events: 6,
    err_gtfs_m: 40,
    err_found_m: 6.5,
    started_at: '2026-11-07T08:00:00+00:00',
    finished_at: '2026-11-07T08:02:30+00:00',
    ...overrides,
  };
}

/**
 * Six events: begin (two opening photos), a thought, a look (photo 3), a refused call, the
 * checklist of candidate 1, then an unknown kind. A short bus path, two candidates.
 */
export function exploration(runId = 'f1', overrides: Partial<Exploration> = {}): Exploration {
  return {
    ...summary(runId),
    report: 'I found the stop.\nIt has a sign.',
    positions: [
      { kind: 'gtfs', lat: 41.9, lon: 12.5, label: 'GTFS', error_m: 40 },
      { kind: 'verified', lat: 41.9003, lon: 12.5, label: 'Verified', error_m: null },
      {
        kind: 'estimate',
        lat: 41.9004,
        lon: 12.5001,
        label: 'Submitted position',
        error_m: 6.5,
      },
    ],
    osm_features: [],
    limits: { along_from: -400, along_to: 400 },
    path: [
      [41.8995, 12.4995],
      [41.9, 12.5],
      [41.9005, 12.5005],
    ],
    candidates: [candidate(1), candidate(2, { status: 'rejected', evidence: null, checklist: {} })],
    photo_list: [photo(1), photo(2), photo(3, { opening: false, toward: 'across' })],
    stop_photos: [],
    close_up: null,
    event_list: [
      event(1, {
        kind: 'begin',
        summary: 'STOP f1: Stop f1',
        photos: [1, 2],
        photos_used: 2,
        budget_used: 2,
        raw: { request: {}, response: 'STOP f1: Stop f1\nSearch limits: -400 m to +400 m.' },
      }),
      event(2, {
        kind: 'thought',
        summary: 'I will look ahead.',
        photos_used: 2,
        budget_used: 2,
        raw: { request: null, response: 'I will look ahead.' },
      }),
      event(3, {
        kind: 'look',
        summary: 'PHOTO 3: from the panorama at +5 m',
        photos: [3],
        photos_used: 3,
        budget_used: 3,
        raw: {
          request: { from_m: 5, toward: 'forward', target_m: null },
          response: 'PHOTO 3: from the panorama at +5 m\nsecond line',
        },
      }),
      event(4, {
        kind: 'tool_error',
        summary: 'ERROR: photo must be an integer',
        error: 'photo must be an integer',
        photos_used: 3,
        budget_used: 3,
        raw: {
          request: { tool: 'mcp__explorer__mark_clear', photo: 'x' },
          response: 'photo must be an integer',
        },
      }),
      event(5, {
        kind: 'answer_checklist',
        summary: 'Candidate 1 CONFIRMED',
        photos_used: 3,
        budget_used: 3,
        raw: { request: { candidate: 1, cotral_logo: 'yes' }, response: 'Candidate 1 CONFIRMED' },
      }),
      event(6, { kind: 'mystery', summary: 'Something new', photos_used: 3, budget_used: 3 }),
    ],
    ...overrides,
  };
}

/**
 * A sweep-harness run: the opening sweep (photos 1-2), a zoom into photo 1 (photo 3), a
 * confirmation (photo 4) whose candidate carries the confirmer's note. 12 sweeps, 1 used.
 */
export function sweepExploration(runId = 'n1', overrides: Partial<Exploration> = {}): Exploration {
  return exploration(runId, {
    photos: 4,
    max_photos: 12,
    budget_unit: 'sweeps',
    budget_used: 1,
    budget_max: 12,
    zooms_used: 1,
    confirms_used: 1,
    candidates: [candidate(1, { confirmer_note: 'A blue Cotral pole.', confirm_photo: 4 })],
    photo_list: [
      photo(1, { toward: 'sweep_ahead', shot: 1, width: 1536, height: 768, opening: true }),
      photo(2, { toward: 'sweep_behind', shot: 1, width: 1536, height: 768, opening: true }),
      photo(3, { toward: 'zoom', fov: 12.5, parent: 1, width: 768, height: 768, opening: false }),
      photo(4, { toward: 'confirm', fov: 20, width: 768, height: 768, opening: false }),
    ],
    event_list: [
      event(1, {
        kind: 'begin',
        summary: 'STOP n1: Stop n1',
        photos: [1, 2],
        photos_used: 2,
        budget_used: 1,
      }),
      event(2, {
        kind: 'zoom',
        summary: 'PHOTO 3: zoom',
        photos: [3],
        photos_used: 3,
        budget_used: 1,
      }),
      event(3, {
        kind: 'confirm',
        summary: 'Candidate 1 CONFIRMED',
        photos: [4],
        photos_used: 4,
        budget_used: 1,
        raw: { request: { candidate: 1, from_m: null }, response: 'Candidate 1 CONFIRMED' },
      }),
    ],
    ...overrides,
  });
}

/**
 * An images-harness run: two single-photo sweeps (photos 1-2), a zoom into photo 2 (photo 3)
 * that the candidate was confirmed on (no confirm photo), then the two stop photos (4-5, the
 * second one from the cache). 3 of 12 images used, 4 billed.
 */
export function imagesExploration(runId = 'i1', overrides: Partial<Exploration> = {}): Exploration {
  const shot = { width: 640, height: 640, billed: true, opening: false };
  return exploration(runId, {
    photos: 5,
    max_photos: 14,
    budget_unit: 'images',
    budget_used: 3,
    budget_max: 12,
    zooms_used: 1,
    confirms_used: 1,
    billed_used: 4,
    stop_photos_used: 2,
    stop_photos: [4, 5],
    close_up: 3,
    candidates: [candidate(1, { confirmer_note: 'A blue Cotral pole.', confirm_photo: 3 })],
    photo_list: [
      photo(1, { ...shot, toward: 'sweep_ahead', shot: 1, opening: true }),
      photo(2, { ...shot, toward: 'sweep_behind', shot: 2 }),
      photo(3, { ...shot, toward: 'zoom', fov: 12.5, parent: 2 }),
      photo(4, { ...shot, toward: 'stop_photo', fov: 70 }),
      photo(5, { ...shot, toward: 'stop_photo', fov: 60, billed: false }),
    ],
    event_list: [
      event(1, { kind: 'begin', summary: 'STOP i1', photos: [1], photos_used: 1, budget_used: 1 }),
      event(2, { kind: 'sweep', summary: 'PHOTO 2', photos: [2], photos_used: 2, budget_used: 2 }),
      event(3, { kind: 'zoom', summary: 'PHOTO 3', photos: [3], photos_used: 3, budget_used: 3 }),
      event(4, {
        kind: 'confirm',
        summary: 'Candidate 1 CONFIRMED',
        photos_used: 3,
        budget_used: 3,
        raw: { request: { candidate: 1 }, response: 'Candidate 1 CONFIRMED' },
      }),
      event(5, {
        kind: 'submit_found',
        summary: 'Submitted.',
        photos: [4, 5],
        photos_used: 5,
        budget_used: 3,
      }),
    ],
    ...overrides,
  });
}
