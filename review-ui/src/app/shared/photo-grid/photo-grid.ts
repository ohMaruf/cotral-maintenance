import { ChangeDetectionStrategy, Component, booleanAttribute, input, output } from '@angular/core';
import { Photo } from '../../core/api/api.types';

@Component({
  selector: 'app-photo-grid',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[class.fill]': 'fill()' },
  templateUrl: './photo-grid.html',
  styleUrl: './photo-grid.scss',
})
export class PhotoGrid {
  readonly photos = input.required<Photo[]>();
  readonly stopName = input<string>('');
  readonly size = input<'sm' | 'lg'>('lg');
  readonly fill = input(false, { transform: booleanAttribute });
  readonly photoSelected = output<number>();
}
