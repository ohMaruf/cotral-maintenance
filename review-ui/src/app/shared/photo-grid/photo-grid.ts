import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { Photo } from '../../core/api/api.types';

/** Thumbnails that each open the viewer: emits the index of the clicked photo. */
@Component({
  selector: 'app-photo-grid',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './photo-grid.html',
  styleUrl: './photo-grid.scss',
})
export class PhotoGrid {
  readonly photos = input.required<Photo[]>();
  /** Used in the accessible label: "Photo 1 of 4 of <stopName>". */
  readonly stopName = input<string>('');
  readonly size = input<'sm' | 'lg'>('lg');
  readonly photoSelected = output<number>();
}
