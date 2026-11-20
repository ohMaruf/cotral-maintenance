import { ChangeDetectionStrategy, Component, input } from '@angular/core';

export type BadgeTone = 'ok' | 'warn' | 'bad' | 'neutral';

@Component({
  selector: 'app-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: '<span [class]="\'badge \' + tone()"><ng-content /></span>',
  styles: `
    @use 'theme' as *;

    .badge {
      display: inline-flex;
      align-items: center;
      gap: $space-1;
      color: $color-text-muted;
      font-size: $text-sm;
      white-space: nowrap;

      &::before {
        content: '';
        flex: none;
        width: 6px;
        height: 6px;
        background: $color-text-faint;
      }
    }

    .ok::before {
      background: $color-ok;
    }

    .warn::before {
      background: $color-warn;
    }

    .bad {
      color: $color-danger;

      &::before {
        background: $color-danger;
      }
    }
  `,
})
export class Badge {
  readonly tone = input<BadgeTone>('neutral');
}
