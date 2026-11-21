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
  model: string | null;
}

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
  readonly harness = input<string | null>(null);

  private readonly collapsed = signal<ReadonlySet<string>>(new Set());

  protected readonly groups = computed(() =>
    groupRuns(this.runs()).map((g) => {
      const defaultModel = commonModel(g.runs);
      return {
        version: g.version,
        model: defaultModel,
        label: versionLabel(g.version),
        found: g.found,
        count: g.runs.length,
        open: !this.collapsed().has(g.version),
        items: g.runs.map((run): Item => ({
          run,
          outcome: outcomeInfo(run.outcome),
          budget: budgetLabel(run.budget_used, run.budget_max, run.budget_unit),
          errors: `${formatMeters(run.err_gtfs_m)} → ${formatMeters(run.err_found_m)}`,
          model: run.model && run.model !== defaultModel ? run.model : null,
        })),
      };
    }),
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

function commonModel(runs: ExplorationSummary[]): string | null {
  const counts = new Map<string, number>();
  for (const { model } of runs) if (model) counts.set(model, (counts.get(model) ?? 0) + 1);
  let best: string | null = null;
  let bestCount = 0;
  for (const [model, count] of counts) {
    if (count > bestCount) {
      best = model;
      bestCount = count;
    }
  }
  return best;
}
