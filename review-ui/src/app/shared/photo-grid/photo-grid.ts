import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { Photo } from '../../core/api/api.types';

@Component({
  selector: 'app-photo-grid',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './photo-grid.html',
  styleUrl: './photo-grid.scss',
})
export class PhotoGrid {
  readonly photos = input.required<Photo[]>();
  readonly stopName = input<string>('');
  readonly size = input<'sm' | 'lg'>('lg');
  readonly photoSelected = output<number>();
}
