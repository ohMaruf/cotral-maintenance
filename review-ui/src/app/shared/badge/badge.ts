import { ChangeDetectionStrategy, Component, input } from '@angular/core';

export type BadgeTone = 'ok' | 'warn' | 'bad' | 'neutral';

/** Small status pill. The label is always text, so colour is never the only signal. */
@Component({
  selector: 'app-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<span class="badge" [class]="\'badge \' + tone()"><ng-content /></span>',
  styles: `
    .badge {
      display: inline-block;
      padding: 1px var(--space-2);
      border: 1px solid var(--color-border-strong);
      border-radius: var(--radius-pill);
      background: var(--color-surface-2);
      color: var(--color-text);
      font-size: var(--text-xs);
      font-weight: 600;
      white-space: nowrap;
    }

    .ok {
      border-color: var(--color-ok);
      background: var(--color-ok-bg);
    }

    .warn {
      border-color: var(--color-warn-border);
      background: var(--color-warn-bg);
    }

    .bad {
      border-color: var(--color-danger);
      background: var(--color-danger-bg);
    }
  `,
})
export class Badge {
  readonly tone = input<BadgeTone>('neutral');
}
