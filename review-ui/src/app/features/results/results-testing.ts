import { ResultRow, RunInfo } from '../../core/api/api.types';

/** A ranked, found and scored row; override what a test is about. */
export function resultRow(id: string, overrides: Partial<ResultRow> = {}): ResultRow {
  return {
    rank: 1,
    stop_id: id,
    name: `Stop ${id}`,
    needs_review: false,
    review_reason: '',
    condition: 0.45,
    has_shelter: 0.95,
    shelter: 0.75,
    has_seating: 0.9,
    seating: 0.5,
    waiting_area: 0.75,
    accessibility: 0.5,
    has_lamp: 0.7,
    stop_visible: 0.9,
    missing: [],
    status: 'found',
    explore_reason: 'the explorer ended: outcome',
    evidence: 'cotral_sign',
    plate_text: null,
    lat: 41.9,
    lon: 12.5,
    found_from_gtfs_m: 42.4,
    position_basis: 'triangulated',
    scan_date: '2025-06',
    start_source: 'osm',
    start_lat: 41.9,
    start_lon: 12.5,
    gtfs_lat: 41.9,
    gtfs_lon: 12.5,
    explorer_model: 'qwen3.8-27b',
    scorer_model: 'imajev-4b',
    photos: [`/api/explorations/${id}/photos/${'a'.repeat(64)}.jpg`],
    ...overrides,
  };
}

export const RUN_INFO: RunInfo = {
  name: 'smoke-local',
  stops: 4,
  ingested: { osm: 2, gtfs: 2 },
  explored: { found: 2, not_found: 1, no_imagery: 1 },
  scored: 2,
  billed: { static: 6, tiles: 40 },
  profiles: [{ key: '1', name: 'local-smoke-gguf', description: 'MacBook smoke test' }],
};
