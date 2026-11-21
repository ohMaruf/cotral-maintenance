import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

@Component({
  selector: 'app-list-toolbar',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './list-toolbar.html',
  styleUrl: './list-toolbar.scss',
})
export class ListToolbar {
  readonly inputId = input.required<string>();
  readonly query = input('');
  readonly shown = input.required<number>();
  readonly total = input.required<number>();
  readonly sorted = input(false);
  readonly queryChange = output<string>();
  readonly sortCleared = output<void>();
}
