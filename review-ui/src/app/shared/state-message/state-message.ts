import { ChangeDetectionStrategy, Component, booleanAttribute, input, output } from '@angular/core';

export type StateKind = 'loading' | 'error' | 'empty' | 'done';

@Component({
  selector: 'app-state-message',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[class.page]': 'page()' },
  templateUrl: './state-message.html',
  styleUrl: './state-message.scss',
})
export class StateMessage {
  readonly kind = input.required<StateKind>();
  readonly title = input.required<string>();
  readonly message = input<string>();
  readonly actionLabel = input<string>();
  readonly page = input(false, { transform: booleanAttribute });
  readonly action = output<void>();
}
