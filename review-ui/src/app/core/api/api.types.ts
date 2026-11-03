// Hand-written mirror of docs/review-api.md. Change the contract first.

export type CategoryKind = 'level' | 'probability';

export interface Category {
  key: string;
  label: string;
  kind: CategoryKind;
  description: string;
}

export interface Model {
  key: string;
  label: string;
  description: string;
}

export interface Catalog {
  categories: Category[];
  models: Model[];
}

export interface Photo {
  view: string;
  description: string;
  url: string;
  distance_m: number | null;
  heading: number | null;
  /** Must be displayed with the photo (Street View terms). */
  copyright: string | null;
}

export interface StopSummary {
  stop_id: string;
  name: string;
  lat: number;
  lon: number;
  /** "2025-06" */
  imagery_date: string | null;
  photos: Photo[];
}

/** model key -> category key -> value; a model or category may be missing. */
export type ScoreMap = Record<string, Record<string, number>>;
/** model key -> category key -> one-sentence reason. */
export type EvidenceMap = Record<string, Record<string, string>>;

export interface StopDetail extends StopSummary {
  scores: ScoreMap;
  evidence: EvidenceMap;
}

export interface Progress {
  judged: number;
  skipped: number;
  remaining: number;
}

export interface Judgment {
  id: string;
  created_at: string;
  left: string;
  right: string;
  winner: string | null;
  loser: string | null;
  rater: string | null;
  decision_ms: number | null;
}

export interface Pair {
  left: StopSummary;
  right: StopSummary;
}

export interface NextPairResponse {
  pair: Pair | null;
  progress: Progress;
}

export interface JudgmentRequest {
  left: string;
  right: string;
  winner: string | null;
  rater?: string | null;
  decision_ms?: number | null;
}

export interface JudgmentResponse {
  judgment: Judgment;
  left: StopDetail;
  right: StopDetail;
  progress: Progress;
}
