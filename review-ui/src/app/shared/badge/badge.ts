import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import {
  LucideCircleCheck,
  LucideCircleDashed,
  LucideCircleX,
  LucideTriangleAlert,
} from '@lucide/angular';

export type BadgeTone = 'ok' | 'warn' | 'bad' | 'neutral';
export type BadgeIcon = 'found' | 'missing' | 'none' | 'alert';

@Component({
  selector: 'app-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideCircleCheck, LucideCircleDashed, LucideCircleX, LucideTriangleAlert],
  template: `
    <span [class]="'badge ' + tone() + (icon() ? ' iconic' : '')">
      @switch (icon()) {
        @case ('found') {
          <svg lucideCircleCheck size="14" aria-hidden="true"></svg>
        }
        @case ('missing') {
          <svg lucideCircleDashed size="14" aria-hidden="true"></svg>
        }
        @case ('none') {
          <svg lucideCircleX size="14" aria-hidden="true"></svg>
        }
        @case ('alert') {
          <svg lucideTriangleAlert size="14" aria-hidden="true"></svg>
        }
      }
      <ng-content />
    </span>
  `,
  styles: `
    @use 'theme' as *;

    .badge {
      display: inline-flex;
      align-items: center;
      gap: $space-1;
      color: $color-text-muted;
      font-size: $text-sm;
      white-space: nowrap;

      &:not(.iconic)::before {
        content: '';
        flex: none;
        width: 6px;
        height: 6px;
        background: $color-text-faint;
      }
    }

    .ok:not(.iconic)::before {
      background: $color-ok;
    }

    .warn:not(.iconic)::before {
      background: $color-warn;
    }

    .bad {
      color: $color-danger;

      &:not(.iconic)::before {
        background: $color-danger;
      }
    }

    .iconic.ok svg {
      color: $color-ok;
    }

    .iconic.warn svg {
      color: $color-warn;
    }
  `,
})
export class Badge {
  readonly tone = input<BadgeTone>('neutral');
  readonly icon = input<BadgeIcon | null>(null);
}
