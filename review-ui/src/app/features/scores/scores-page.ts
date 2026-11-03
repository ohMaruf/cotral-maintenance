import { rxResource } from '@angular/core/rxjs-interop';
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { Router } from '@angular/router';
import { forkJoin } from 'rxjs';
import { ApiError, toApiError } from '../../core/api/api-error';
import { ApiService } from '../../core/api/api.service';
import { Category, Model, StopDetail } from '../../core/api/api.types';
import { modelsDisagree } from '../../shared/lib/disagreement';
import {
  SortDirection,
  SortKey,
  filterStops,
  parseSort,
  scoreOf,
  serializeSort,
  sortStops,
} from '../../shared/lib/scores';
import { PhotoGrid } from '../../shared/photo-grid/photo-grid';
import { ScoreBar } from '../../shared/score-bar/score-bar';
import { StateMessage } from '../../shared/state-message/state-message';
import { formatCoordinates, formatImageryDate, mapsUrl } from '../../shared/lib/format';
import { PhotoViewerService } from '../photo-viewer/photo-viewer.service';

interface Cell {
  model: Model;
  value: number | undefined;
  evidence: string | undefined;
}

interface CategoryCells {
  category: Category;
  disagree: boolean;
  cells: Cell[];
}

interface Row {
  stop: StopDetail;
  date: string;
  coords: string;
  map: string;
  categories: CategoryCells[];
}

/** Table of every stop with both models' scores. Sort and filter live in the URL. */
@Component({
  selector: 'app-scores-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PhotoGrid, ScoreBar, StateMessage],
  templateUrl: './scores-page.html',
  styleUrl: './scores-page.scss',
})
export class ScoresPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly viewer = inject(PhotoViewerService);

  // Bound from the query string by withComponentInputBinding().
  readonly sort = input<string | undefined>();
  readonly dir = input<string | undefined>();
  readonly q = input<string | undefined>();

  protected readonly data = rxResource({
    stream: () => forkJoin({ catalog: this.api.catalog(), stops: this.api.stops() }),
  });

  protected readonly error = computed<ApiError | null>(() =>
    this.data.error() ? toApiError(this.data.error()) : null,
  );
  protected readonly categories = computed(() => this.data.value()?.catalog.categories ?? []);
  protected readonly models = computed(() => this.data.value()?.catalog.models ?? []);
  protected readonly total = computed(() => this.data.value()?.stops.length ?? 0);

  protected readonly query = computed(() => this.q() ?? '');
  protected readonly sortKey = computed<SortKey | null>(() =>
    parseSort(this.sort(), this.categories(), this.models()),
  );
  protected readonly direction = computed<SortDirection>(() =>
    this.dir() === 'asc' ? 'asc' : 'desc',
  );

  protected readonly rows = computed<Row[]>(() => {
    const value = this.data.value();
    if (!value) return [];
    const { categories, models } = value.catalog;
    let stops = filterStops(value.stops, this.query());
    const key = this.sortKey();
    if (key) stops = sortStops(stops, key, this.direction(), models);
    return stops.map((stop) => ({
      stop,
      date: formatImageryDate(stop.imagery_date),
      coords: formatCoordinates(stop.lat, stop.lon),
      map: mapsUrl(stop.lat, stop.lon),
      categories: categories.map((category) => {
        const cells = models.map((model) => ({
          model,
          value: scoreOf(stop.scores, model.key, category.key),
          evidence: stop.evidence[model.key]?.[category.key],
        }));
        return {
          category,
          cells,
          disagree: modelsDisagree(
            cells.map((c) => c.value),
            category.kind,
          ),
        };
      }),
    }));
  });

  protected reload(): void {
    this.data.reload();
  }

  protected setQuery(value: string): void {
    void this.router.navigate([], {
      queryParams: { q: value.trim() ? value : null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  /** Clicking the active column flips the direction; a new column starts worst-first. */
  protected setSort(category: string, model: string): void {
    const current = this.sortKey();
    const same = current?.category === category && current.model === model;
    const dir: SortDirection = same && this.direction() === 'desc' ? 'asc' : 'desc';
    void this.router.navigate([], {
      queryParams: { sort: serializeSort({ category, model }), dir },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  protected clearSort(): void {
    void this.router.navigate([], {
      queryParams: { sort: null, dir: null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  /** aria-sort / indicator state for a column. */
  protected sortState(category: string, model: string): 'ascending' | 'descending' | 'none' {
    const k = this.sortKey();
    if (!k || k.category !== category || k.model !== model) return 'none';
    return this.direction() === 'asc' ? 'ascending' : 'descending';
  }

  protected openPhoto(stop: StopDetail, index: number): void {
    void this.viewer.open(stop.photos, index, stop.name);
  }
}
