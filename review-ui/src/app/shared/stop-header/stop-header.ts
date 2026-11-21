import { LucideExternalLink } from '@lucide/angular';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { StopSummary } from '../../core/api/api.types';
import { formatCoordinates, formatImageryDate, mapsUrl } from '../lib/format';

@Component({
  selector: 'app-stop-header',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideExternalLink],
  templateUrl: './stop-header.html',
  styleUrl: './stop-header.scss',
})
export class StopHeader {
  readonly stop = input.required<StopSummary>();
  readonly level = input<2 | 3>(2);

  protected readonly date = computed(() => formatImageryDate(this.stop().imagery_date));
  protected readonly coords = computed(() => formatCoordinates(this.stop().lat, this.stop().lon));
  protected readonly map = computed(() => mapsUrl(this.stop().lat, this.stop().lon));
}
