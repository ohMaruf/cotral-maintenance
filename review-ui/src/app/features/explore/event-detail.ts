import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import {
  Exploration,
  ExplorationCandidate,
  ExplorationEvent,
  ExplorationPhoto,
} from '../../core/api/api.types';
import {
  budgetLabel,
  formatMeters,
  prettyJson,
  towardLabel,
} from '../../shared/lib/explore-format';
import { formatHeading, formatImageryDate } from '../../shared/lib/format';
import { argRows, checklistRows, eventKindInfo, resultText } from './event-kind';
import { photoByIndex } from './explore-view';

interface Fact {
  label: string;
  value: string;
}

export const CHECKLIST_ANSWERS = ['yes', 'no', 'unsure'] as const;

function photoFacts(p: ExplorationPhoto, all: ExplorationPhoto[]): Fact[] {
  return [
    { label: 'Pano id', value: p.pano_id },
    { label: 'Date', value: formatImageryDate(p.date) },
    { label: 'Heading', value: formatHeading(p.heading) ?? '–' },
    { label: 'Field of view', value: `${Math.round(p.fov)}°` },
    { label: 'Pitch', value: `${Math.round(p.pitch)}°` },
    { label: 'Along the path', value: formatMeters(p.along_m) },
    { label: 'Right of the path', value: formatMeters(p.right_m) },
    { label: 'Looking', value: towardLabel(p, all) },
    ...(p.width && p.height ? [{ label: 'Size', value: `${p.width}×${p.height}` }] : []),
    ...(p.source === 'tiles'
      ? [{ label: 'Source', value: `Map Tiles (${p.tiles} tiles paid)` }]
      : []),
    ...(p.shot > 0 ? [{ label: 'Sweep', value: `#${p.shot}` }] : []),
    { label: 'Opening photo', value: p.opening ? 'yes (before the first turn)' : 'no' },
  ];
}

/**
 * One event in full: the model's words for a thought; for a tool call its name, arguments
 * and full result, the photos taken, and the candidate's checklist (and the confirmer's note) for answer_checklist and confirm.
 * Unknown kinds get the same generic treatment, plus the raw request and response.
 */
@Component({
  selector: 'app-event-detail',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './event-detail.html',
  styleUrl: './event-detail.scss',
})
export class EventDetail {
  readonly event = input.required<ExplorationEvent>();
  readonly run = input.required<Exploration>();
  /** A photo (by index) was clicked: open it full size. */
  readonly photoOpen = output<number>();

  protected readonly answers = CHECKLIST_ANSWERS;
  protected readonly kind = computed(() => eventKindInfo(this.event().kind, this.event().error));
  protected readonly budget = computed(() =>
    budgetLabel(this.event().budget_used, this.run().budget_max, this.run().budget_unit),
  );
  protected readonly args = computed(() => argRows(this.event().raw.request));
  protected readonly result = computed(() => resultText(this.event()));
  protected readonly photos = computed(() =>
    this.event()
      .photos.map((i) => photoByIndex(this.run(), i))
      .filter((p): p is ExplorationPhoto => p !== null)
      .map((photo) => ({ photo, facts: photoFacts(photo, this.run().photo_list) })),
  );

  /** The candidate an answer_checklist call is about (by its `candidate` argument). */
  protected readonly candidate = computed<ExplorationCandidate | null>(() => {
    const e = this.event();
    // answer_checklist (old runs) or confirm (the independent confirmer's checklist).
    if (e.kind !== 'answer_checklist' && e.kind !== 'confirm') return null;
    const request = e.raw.request as { candidate?: unknown } | null;
    const c = this.run().candidates.find((c) => c.index === Number(request?.candidate)) ?? null;
    // An old run's confirm only took a photo: it has no checklist to show.
    return e.kind === 'confirm' && c && !c.confirmer_note && Object.keys(c.checklist).length === 0
      ? null
      : c;
  });
  protected readonly checklist = computed(() => {
    const c = this.candidate();
    return c ? checklistRows(c.checklist) : [];
  });

  // Raw JSON can be large: format it only while its section is open. The open state
  // survives stepping to the next event, which is what you want when comparing.
  protected readonly requestOpen = signal(false);
  protected readonly responseOpen = signal(false);
  protected readonly requestJson = computed(() =>
    this.requestOpen() ? prettyJson(this.event().raw.request) : '',
  );
  protected readonly responseJson = computed(() =>
    this.responseOpen() ? prettyJson(this.event().raw.response) : '',
  );

  protected toggle(which: 'request' | 'response', open: boolean): void {
    (which === 'request' ? this.requestOpen : this.responseOpen).set(open);
  }
}
