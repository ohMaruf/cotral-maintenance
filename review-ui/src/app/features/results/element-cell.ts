import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { CategoryKind } from '../../core/api/api.types';
import { formatScore } from '../../shared/lib/format';
import { ScoreBar } from '../../shared/score-bar/score-bar';

@Component({
  selector: 'app-element-cell',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ScoreBar],
  templateUrl: './element-cell.html',
  styleUrl: './element-cell.scss',
})
export class ElementCell {
  readonly label = input.required<string>();
  readonly absent = input(false);
  readonly presence = input<number | undefined>();
  readonly value = input<number | undefined>();
  readonly kind = input<CategoryKind>('condition');
  readonly presenceOnly = input(false);
  readonly evidence = input<string | undefined>();

  protected readonly presenceText = computed(() =>
    this.presence() === undefined ? '' : formatScore(this.presence()),
  );
  protected readonly detail = computed(() =>
    this.presenceText()
      ? `${this.absent() ? 'Missing' : 'Present'}, probability ${this.presenceText()}`
      : '',
  );
  protected readonly barEvidence = computed(
    () => [this.detail(), this.evidence()].filter(Boolean).join('\n') || undefined,
  );
  protected readonly title = computed(() => `${this.label()}: ${this.detail() || 'no data'}`);
}
