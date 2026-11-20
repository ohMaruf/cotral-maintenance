import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RaterService } from '../../core/services/rater.service';

@Component({
  selector: 'app-rater-field',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <label for="rater-name">Rater</label>
    <input
      id="rater-name"
      type="text"
      autocomplete="off"
      placeholder="optional name"
      maxlength="60"
      [value]="rater.name()"
      (input)="rater.set($any($event.target).value)"
    />
  `,
  styleUrl: './rater-field.scss',
})
export class RaterField {
  protected readonly rater = inject(RaterService);
}
