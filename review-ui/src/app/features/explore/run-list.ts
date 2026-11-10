import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ExplorationSummary } from '../../core/api/api.types';
import {
  budgetLabel,
  formatMeters,
  outcomeInfo,
  versionLabel,
} from '../../shared/lib/explore-format';
import { Badge } from '../../shared/badge/badge';
import { groupRuns } from './explore-view';

interface Item {
  run: ExplorationSummary;
  outcome: { label: string; tone: 'ok' | 'warn' | 'bad' | 'neutral' };
  budget: string;
  errors: string;
}

/** The runs, grouped by harness version (newest first, each group collapsible); links so each opens in its own tab. */
@Component({
  selector: 'app-run-list',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, Badge],
  templateUrl: './run-list.html',
  styleUrl: './run-list.scss',
})
export class RunList {
  readonly runs = input.required<ExplorationSummary[]>();
  readonly selectedId = input<string | null>(null);
  /** The version filter, kept in the links so it survives opening a run. */
  readonly harness = input<string | null>(null);

  private readonly collapsed = signal<ReadonlySet<string>>(new Set());

  protected readonly groups = computed(() =>
    groupRuns(this.runs()).map((g) => ({
      version: g.version,
      label: versionLabel(g.version),
      summary: `${g.found}/${g.runs.length} found`,
      count: g.runs.length,
      open: !this.collapsed().has(g.version),
      items: g.runs.map((run): Item => ({
        run,
        outcome: outcomeInfo(run.outcome),
        budget: budgetLabel(run.budget_used, run.budget_max, run.budget_unit),
        errors: `${formatMeters(run.err_gtfs_m)} → ${formatMeters(run.err_found_m)}`,
      })),
    })),
  );

  protected readonly query = computed(() => (this.harness() ? { harness: this.harness() } : {}));

  protected toggle(version: string): void {
    this.collapsed.update((set) => {
      const next = new Set(set);
      if (!next.delete(version)) next.add(version);
      return next;
    });
  }
}
