import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { Exploration } from '../../core/api/api.types';
import {
  billedLabel,
  budgetDetail,
  formatMeters,
  formatTimestamp,
  modelsLabel,
  outcomeInfo,
  runDuration,
  shortCommit,
  startLabel,
  tilesLabel,
  versionLabel,
} from '../../shared/lib/explore-format';
import { Badge } from '../../shared/badge/badge';

/** Reports longer than this start collapsed. */
export const LONG_REPORT_CHARS = 400;

/** Run summary: stop, outcome and reason, model, errors, timing, limits and the model's report. */
@Component({
  selector: 'app-run-header',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Badge],
  templateUrl: './run-header.html',
  styleUrl: './run-header.scss',
})
export class RunHeader {
  readonly run = input.required<Exploration>();

  protected readonly outcome = computed(() => outcomeInfo(this.run().outcome));
  protected readonly running = computed(() => this.run().outcome === 'running');
  protected readonly budget = computed(() => budgetDetail(this.run()));
  protected readonly billed = computed(() => billedLabel(this.run()));
  protected readonly version = computed(() => versionLabel(this.run().harness.version));
  protected readonly commit = computed(() => shortCommit(this.run().harness.git_commit));
  protected readonly models = computed(() => modelsLabel(this.run().harness));
  protected readonly tiles = computed(() => tilesLabel(this.run()));
  protected readonly start = computed(() => startLabel(this.run().start_kind));
  protected readonly gtfsError = computed(() => formatMeters(this.run().err_gtfs_m));
  protected readonly foundError = computed(() => formatMeters(this.run().err_found_m));
  protected readonly started = computed(() => formatTimestamp(this.run().started_at));
  protected readonly finished = computed(() => formatTimestamp(this.run().finished_at));
  protected readonly duration = computed(
    () => runDuration(this.run().started_at, this.run().finished_at) ?? '–',
  );
  protected readonly limits = computed(() => {
    const { along_from, along_to } = this.run().limits;
    return `${along_from.toFixed(0)} m … ${along_to.toFixed(0)} m along the path`;
  });
  protected readonly longReport = computed(
    () => (this.run().report?.length ?? 0) > LONG_REPORT_CHARS,
  );
}
