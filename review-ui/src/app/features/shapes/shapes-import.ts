import { ShapeVerdictRequest, ShapeVerdictValue } from '../../core/api/api.types';
import { parseCsvRecords } from '../../shared/lib/csv';

const VALUES: readonly string[] = ['on_route', 'off_route', 'unclear'];

export interface ImportRequest {
  stopId: string;
  body: ShapeVerdictRequest;
}

export interface ImportPlan {
  requests: ImportRequest[];
  skipped: number;
}

export function planImport(
  csv: string,
  knownIds: ReadonlySet<string>,
  rater: string | null,
): ImportPlan {
  const requests: ImportRequest[] = [];
  let skipped = 0;
  for (const row of parseCsvRecords(csv)) {
    const stopId = (row['stop_id'] ?? '').trim();
    const raw = (row['verdict'] ?? '').trim();
    const verdict = VALUES.includes(raw) ? (raw as ShapeVerdictValue) : null;
    const note = (row['note'] ?? '').trim();
    if (!knownIds.has(stopId) || (verdict === null && note === '')) {
      skipped++;
      continue;
    }
    requests.push({ stopId, body: { verdict, note, rater } });
  }
  return { requests, skipped };
}
