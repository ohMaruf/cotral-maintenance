import { ShapeVerdictRequest, ShapeVerdictValue } from '../../core/api/api.types';
import { parseCsvRecords } from '../../shared/lib/csv';

const VALUES: readonly string[] = ['on_route', 'off_route', 'unclear'];

export interface ImportRequest {
  stopId: string;
  body: ShapeVerdictRequest;
}

export interface ImportPlan {
  requests: ImportRequest[];
  /** Rows without a verdict or note, or for a stop that is not in the check. */
  skipped: number;
}

/**
 * Plans the import of a CSV exported by the old page (`stop_id,offset_m,verdict,
 * note,...`) or by the BFF: one request per row that has a verdict or a note, for a
 * stop in `knownIds`. An unrecognised verdict is dropped (the note is still kept).
 */
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
