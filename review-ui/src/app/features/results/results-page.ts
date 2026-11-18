import { rxResource } from '@angular/core/rxjs-interop';
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import { ApiError, toApiError } from '../../core/api/api-error';
import { ApiService } from '../../core/api/api.service';
import { Photo, ResultRow } from '../../core/api/api.types';
import { Badge } from '../../shared/badge/badge';
import { formatMeters, outcomeInfo } from '../../shared/lib/explore-format';
import { formatImageryDate } from '../../shared/lib/format';
import { ScoreBar } from '../../shared/score-bar/score-bar';
import { StateMessage } from '../../shared/state-message/state-message';
import { PhotoViewerService } from '../photo-viewer/photo-viewer.service';
import {
  SCORE_COLUMNS,
  Show,
  SortDirection,
  SortKey,
  billedSummary,
  defaultDirection,
  exploredSummary,
  filterRows,
  parseShow,
  missingText,
  parseSort,
  sortRows,
} from './results-view';

interface Item {
  row: ResultRow;
  status: { label: string; tone: 'ok' | 'warn' | 'bad' | 'neutral' };
  evidence: string;
  moved: string;
  date: string;
  photos: Photo[];
  scores: (number | undefined)[];
  /** Per score column: the stop lacks the element it rates. */
  gone: boolean[];
  missing: string;
}

const SHOWS: { value: Show; label: string }[] = [
  { value: 'all', label: 'All stops' },
  { value: 'ranked', label: 'Ranked' },
  { value: 'review', label: 'Needs review' },
];

/** The photo viewer wants Photo objects; a result row only has the URLs (all Street View). */
function viewerPhotos(row: ResultRow): Photo[] {
  return row.photos.map((url, i) => ({
    view: `stop_photo_${i + 1}`,
    description:
      i === 0 ? 'From the panorama that confirmed the stop' : 'From about 12 m before the stop',
    url,
    distance_m: null,
    heading: null,
    copyright: '© Google',
  }));
}

/**
 * The run's results: its header (size, outcomes, billing, profiles) and the ranked table of
 * every stop, with its photos and scores. Sort, filter and "needs review" live in the URL.
 */
@Component({
  selector: 'app-results-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Badge, RouterLink, ScoreBar, StateMessage],
  templateUrl: './results-page.html',
  styleUrl: './results-page.scss',
})
export class ResultsPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly viewer = inject(PhotoViewerService);

  // Bound from the query string by withComponentInputBinding().
  readonly sort = input<string | undefined>();
  readonly dir = input<string | undefined>();
  readonly show = input<string | undefined>();
  readonly q = input<string | undefined>();

  protected readonly data = rxResource({
    stream: () => forkJoin({ run: this.api.run(), rows: this.api.results() }),
  });

  protected readonly error = computed<ApiError | null>(() =>
    this.data.error() ? toApiError(this.data.error()) : null,
  );
  protected readonly run = computed(() => this.data.value()?.run ?? null);
  protected readonly explored = computed(() => exploredSummary(this.run()?.explored ?? {}));
  protected readonly billed = computed(() => billedSummary(this.run()?.billed ?? {}));
  protected readonly review = computed(
    () => this.data.value()?.rows.filter((r) => r.needs_review).length ?? 0,
  );
  protected readonly total = computed(() => this.data.value()?.rows.length ?? 0);

  protected readonly columns = SCORE_COLUMNS;
  protected readonly shows = SHOWS;
  protected readonly query = computed(() => this.q() ?? '');
  protected readonly showing = computed(() => parseShow(this.show()));
  protected readonly sortKey = computed<SortKey | null>(() => parseSort(this.sort()));
  protected readonly direction = computed<SortDirection>(() => {
    const key = this.sortKey();
    const explicit = this.dir();
    return explicit === 'asc' || explicit === 'desc'
      ? explicit
      : key
        ? defaultDirection(key)
        : 'asc';
  });

  protected readonly items = computed<Item[]>(() => {
    let rows = filterRows(this.data.value()?.rows ?? [], this.showing(), this.query());
    const key = this.sortKey();
    if (key) rows = sortRows(rows, key, this.direction());
    return rows.map((row) => ({
      row,
      status: outcomeInfo(row.status ?? 'not_explored'),
      evidence: (row.evidence ?? '').replaceAll('_', ' '),
      moved: formatMeters(row.found_from_gtfs_m),
      date: row.scan_date ? formatImageryDate(row.scan_date) : '',
      photos: viewerPhotos(row),
      scores: SCORE_COLUMNS.map((c) => row[c.key] ?? undefined),
      gone: SCORE_COLUMNS.map((c) => !!c.element && !!row.missing?.includes(c.element)),
      missing: missingText(row.missing),
    }));
  });

  protected reload(): void {
    this.data.reload();
  }

  protected setQuery(value: string): void {
    this.navigate({ q: value.trim() ? value : null });
  }

  protected setShow(value: Show): void {
    this.navigate({ show: value === 'all' ? null : value });
  }

  /** Clicking the active column flips the direction; a new column starts with its default. */
  protected setSort(key: SortKey): void {
    const flip = this.sortKey() === key;
    const dir: SortDirection = flip
      ? this.direction() === 'asc'
        ? 'desc'
        : 'asc'
      : defaultDirection(key);
    this.navigate({ sort: key, dir });
  }

  protected clearSort(): void {
    this.navigate({ sort: null, dir: null });
  }

  /** aria-sort / indicator state for a column. */
  protected sortState(key: SortKey): 'ascending' | 'descending' | 'none' {
    if (this.sortKey() !== key) return 'none';
    return this.direction() === 'asc' ? 'ascending' : 'descending';
  }

  protected openPhoto(item: Item, index: number): void {
    void this.viewer.open(item.photos, index, item.row.name);
  }

  private navigate(queryParams: Record<string, string | null>): void {
    void this.router.navigate([], { queryParams, queryParamsHandling: 'merge', replaceUrl: true });
  }
}
