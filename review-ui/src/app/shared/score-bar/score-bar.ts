import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { CategoryKind } from '../../core/api/api.types';
import { formatScore } from '../lib/format';
import { fraction, severityColor } from '../lib/severity';

@Component({
  selector: 'app-score-bar',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './score-bar.html',
  styleUrl: './score-bar.scss',
  host: { '[attr.title]': 'tooltip()' },
})
export class ScoreBar {
  readonly value = input<number | undefined>();
  readonly kind = input.required<CategoryKind>();
  readonly label = input<string>('');
  readonly evidence = input<string | undefined>();

  protected readonly missing = computed(() => this.value() === undefined);
  protected readonly text = computed(() => formatScore(this.value()));
  protected readonly width = computed(() => {
    const v = this.value();
    return v === undefined ? 0 : fraction(v) * 100;
  });
  protected readonly color = computed(() => {
    const v = this.value();
    return v === undefined ? 'transparent' : severityColor(v, this.kind());
  });
  protected readonly tooltip = computed(() => {
    const head = this.label() ? `${this.label()}: ${this.text()}` : this.text();
    const ev = this.evidence();
    return ev ? `${head}\n${ev}` : head;
  });
  protected readonly aria = computed(() => {
    const v = this.value();
    const base = this.label() || 'Value';
    const main = v === undefined ? `${base}: no score` : `${base}: ${this.text()}`;
    return this.evidence() ? `${main}. ${this.evidence()}` : main;
  });
}
