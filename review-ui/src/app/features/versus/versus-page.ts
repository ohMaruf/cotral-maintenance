import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  viewChild,
} from '@angular/core';
import { Category, Model, StopDetail, StopSummary } from '../../core/api/api.types';
import { ShortcutService } from '../../core/services/shortcut.service';
import { modelsDisagree } from '../../shared/lib/disagreement';
import { formatScore } from '../../shared/lib/format';
import { scoreOf } from '../../shared/lib/scores';
import { PhotoGrid } from '../../shared/photo-grid/photo-grid';
import { ScoreBar } from '../../shared/score-bar/score-bar';
import { StateMessage } from '../../shared/state-message/state-message';
import { StopHeader } from '../../shared/stop-header/stop-header';
import { PhotoViewerService } from '../photo-viewer/photo-viewer.service';
import { Agreement, Choice, OVERALL_CATEGORY, Side, modelAgreement } from './agreement';
import { VersusStore } from './versus-store';

interface RevealCell {
  model: Model;
  value: number | undefined;
  evidence: string | undefined;
}

interface RevealRow {
  category: Category;
  left: RevealCell[];
  right: RevealCell[];
  /** Models disagree about this category for at least one of the stops. */
  disagree: boolean;
}

interface AgreementView {
  model: Model;
  agreement: Agreement;
  text: string;
}

function cellsFor(stop: StopDetail, category: Category, models: Model[]): RevealCell[] {
  return models.map((model) => ({
    model,
    value: scoreOf(stop.scores, model.key, category.key),
    evidence: stop.evidence[model.key]?.[category.key],
  }));
}

function describe(label: string, a: Agreement, overall: Category | undefined): string {
  const fmt = (v: number) => formatScore(v, overall?.kind ?? 'level');
  switch (a.kind) {
    case 'agrees':
      return `${label} agrees (${fmt(a.left)} vs ${fmt(a.right)})`;
    case 'disagrees':
      return `${label} disagrees (${fmt(a.left)} vs ${fmt(a.right)})`;
    case 'tie':
      return `${label} sees a tie (${fmt(a.left)} vs ${fmt(a.right)})`;
    case 'no-pick':
      return `${label}: no pick to compare`;
    case 'no-score':
      return `${label}: no overall score`;
  }
}

@Component({
  selector: 'app-versus-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PhotoGrid, ScoreBar, StateMessage, StopHeader],
  providers: [VersusStore],
  templateUrl: './versus-page.html',
  styleUrl: './versus-page.scss',
})
export class VersusPage {
  protected readonly store = inject(VersusStore);
  private readonly viewer = inject(PhotoViewerService);
  private readonly nextButton = viewChild<ElementRef<HTMLButtonElement>>('nextButton');

  protected readonly reveal = computed(() => {
    const res = this.store.result();
    const catalog = this.store.catalog();
    const choice = this.store.choice();
    if (!res || !catalog || !choice) return null;
    const { categories, models } = catalog;
    const rows: RevealRow[] = categories.map((category) => {
      const left = cellsFor(res.left, category, models);
      const right = cellsFor(res.right, category, models);
      return {
        category,
        left,
        right,
        disagree:
          modelsDisagree(
            left.map((c) => c.value),
            category.kind,
          ) ||
          modelsDisagree(
            right.map((c) => c.value),
            category.kind,
          ),
      };
    });
    const overall = categories.find((c) => c.key === OVERALL_CATEGORY);
    const agreements: AgreementView[] = models.map((model) => {
      const agreement = modelAgreement(res.left.scores, res.right.scores, model.key, choice);
      return { model, agreement, text: describe(model.label, agreement, overall) };
    });
    return { rows, agreements, models };
  });

  constructor() {
    inject(ShortcutService).listen({
      arrowleft: () => this.pick('left'),
      arrowright: () => this.pick('right'),
      s: () => this.pick('skip'),
      enter: () => this.store.next(),
    });
    this.store.start();
    effect(() => {
      // Move focus to "Next pair" once the scores are revealed, so Enter continues.
      if (this.store.phase() === 'revealed') this.nextButton()?.nativeElement.focus();
    });
  }

  protected pick(choice: Choice): void {
    this.store.choose(choice);
  }

  protected side(side: Side): StopSummary | undefined {
    return this.store.pair()?.[side];
  }

  protected openPhoto(stop: StopSummary, index: number): void {
    void this.viewer.open(stop.photos, index, stop.name);
  }
}
