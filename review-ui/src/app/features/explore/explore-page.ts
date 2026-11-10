import { rxResource } from '@angular/core/rxjs-interop';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  signal,
  viewChildren,
} from '@angular/core';
import { Router } from '@angular/router';
import { ApiError, toApiError } from '../../core/api/api-error';
import { ApiService } from '../../core/api/api.service';
import { ExplorationPhoto } from '../../core/api/api.types';
import { ShortcutService } from '../../core/services/shortcut.service';
import { GeoMap } from '../../shared/geo-map/geo-map';
import { OSM_LEGEND, loadShowFeatures, saveShowFeatures } from '../../shared/geo-map/osm-features';
import { towardLabel, toViewerPhoto, versionLabel } from '../../shared/lib/explore-format';
import { StateMessage } from '../../shared/state-message/state-message';
import { PhotoViewerService } from '../photo-viewer/photo-viewer.service';
import { eventKindInfo, timelineLine } from './event-kind';
import { EventDetail } from './event-detail';
import {
  PIN_LETTERS,
  buildExploreLayers,
  exploreBounds,
  photoIndexOfLayer,
} from './explore-layers';
import {
  EventStep,
  adjacentRun,
  groupRuns,
  visibleRuns,
  currentEvent,
  eventOfPhoto,
  orderedEvents,
  parseSeq,
  stepPhotoSeq,
  stepSeq,
} from './explore-view';
import { RunHeader } from './run-header';
import { RunList } from './run-list';

const LEGEND = (
  [
    ['gtfs', 'GTFS'],
    ['places', 'Places'],
    ['verified', 'Verified'],
    ['estimate', 'Submitted position'],
  ] as const
).map(([kind, label]) => ({ kind, label, letter: PIN_LETTERS[kind] }));

const CANDIDATE_LEGEND = [
  { status: 'spotted', label: 'spotted' },
  { status: 'awaiting_checklist', label: 'awaiting checklist' },
  { status: 'confirmed', label: 'confirmed' },
  { status: 'rejected', label: 'rejected' },
];

const FEATURES_KEY = 'explore.osmFeatures';

/**
 * Replays one exploration run step by step: the map of the bus path, candidates and where
 * each photo was taken and looked, a filmstrip, a timeline of the model's thoughts and
 * tool calls in exact order, and the selected event in full. The run is in the path and the event (its `seq`) in `?event=N`.
 */
@Component({
  selector: 'app-explore-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [EventDetail, GeoMap, RunHeader, RunList, StateMessage],
  templateUrl: './explore-page.html',
  styleUrl: './explore-page.scss',
})
export class ExplorePage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly viewer = inject(PhotoViewerService);

  // Bound from the route and query string by withComponentInputBinding().
  readonly runId = input<string | undefined>();
  readonly event = input<string | undefined>();
  /** `?harness=0.6.0`: only the runs of that harness version. */
  readonly harness = input<string | undefined>();

  protected readonly legend = LEGEND;
  protected readonly candidateLegend = CANDIDATE_LEGEND;
  protected readonly osmLegend = OSM_LEGEND;
  protected readonly showFeatures = signal(loadShowFeatures(FEATURES_KEY));

  protected readonly runs = rxResource({ stream: () => this.api.explorations() });
  protected readonly run = rxResource({
    params: () => this.runId(),
    stream: ({ params }) => this.api.exploration(params),
  });

  protected readonly runsError = computed<ApiError | null>(() =>
    this.runs.error() ? toApiError(this.runs.error()) : null,
  );
  protected readonly runError = computed<ApiError | null>(() =>
    this.run.error() ? toApiError(this.run.error()) : null,
  );
  protected readonly allRuns = computed(() => this.runs.value() ?? []);
  /** The runs as listed: of the filtered version, grouped, newest version first. */
  protected readonly runList = computed(() => visibleRuns(this.allRuns(), this.harness() || null));
  protected readonly versionOptions = computed(() => {
    const groups = groupRuns(this.allRuns());
    const options = groups.map((g) => ({
      version: g.version,
      label: versionLabel(g.version),
      runs: g.runs.length,
    }));
    const wanted = this.harness();
    return wanted && !groups.some((g) => g.version === wanted)
      ? [...options, { version: wanted, label: versionLabel(wanted), runs: 0 }]
      : options;
  });
  protected readonly loadedRun = computed(() => (this.run.hasValue() ? this.run.value() : null));

  protected readonly events = computed(() => {
    const run = this.loadedRun();
    return run ? orderedEvents(run) : [];
  });
  protected readonly current = computed(() => currentEvent(this.events(), parseSeq(this.event())));
  protected readonly position = computed(() => {
    const c = this.current();
    return c ? this.events().indexOf(c) + 1 : 0;
  });

  protected readonly rows = computed(() =>
    this.events().map((e) => ({
      event: e,
      kind: eventKindInfo(e.kind, e.error),
      line: timelineLine(e),
    })),
  );
  protected readonly photos = computed(() => {
    const run = this.loadedRun();
    if (!run) return [];
    const used = this.current()?.photos_used ?? 0;
    return [...run.photo_list]
      .sort((a, b) => a.index - b.index)
      .map((photo, i, all) => ({
        photo,
        later: photo.index > used,
        label: towardLabel(photo, all),
        // The photos of one group (the two of an old sweep, or the stop photos) sit together
        // under one tag; a single-photo sweep is a group of one.
        groupStart: groupOf(photo) !== null && groupOf(all[i - 1]) !== groupOf(photo),
        groupEnd: groupOf(photo) !== null && groupOf(all[i + 1]) !== groupOf(photo),
        groupTag: groupTag(photo),
      }));
  });
  /** The harness's photos of the found stop, shown above the strip. */
  protected readonly stopPhotos = computed(() => {
    const run = this.loadedRun();
    if (!run) return [];
    return run.stop_photos
      .map((i) => run.photo_list.find((p) => p.index === i))
      .filter((p): p is ExplorationPhoto => p !== undefined);
  });

  protected readonly layers = computed(() => {
    const run = this.loadedRun();
    if (!run) return [];
    const current = this.current();
    return buildExploreLayers(run, {
      photosUsed: current?.photos_used ?? 0,
      currentPhotos: current?.photos ?? [],
      showOsmFeatures: this.showFeatures(),
    });
  });
  protected readonly bounds = computed(() => {
    const run = this.loadedRun();
    return run ? exploreBounds(run) : null;
  });

  private readonly rowEls = viewChildren<ElementRef<HTMLElement>>('stepEl');

  constructor() {
    inject(ShortcutService).listen({
      arrowleft: () => this.step('prev'),
      arrowright: () => this.step('next'),
      home: () => this.step('first'),
      end: () => this.step('last'),
      ',': () => this.stepPhoto('previous'),
      '.': () => this.stepPhoto('next'),
      '[': () => this.stepRun(-1),
      ']': () => this.stepRun(1),
    });

    // No run in the URL: open the first one (without adding a history entry).
    effect(() => {
      const first = this.runList()[0];
      if (first && !this.runId()) {
        void this.router.navigate(['/explore', first.run_id], {
          ...this.harnessQuery(),
          replaceUrl: true,
        });
      }
    });

    // Keep the selected timeline row in view while stepping with the keyboard.
    effect(() => {
      const seq = this.current()?.seq;
      const el = this.rowEls().find((r) => r.nativeElement.dataset['seq'] === String(seq));
      el?.nativeElement.scrollIntoView?.({ block: 'nearest' });
    });
  }

  protected toggleFeatures(): void {
    this.showFeatures.update((v) => !v);
    saveShowFeatures(FEATURES_KEY, this.showFeatures());
  }

  protected reloadRuns(): void {
    this.runs.reload();
  }

  protected reloadRun(): void {
    this.run.reload();
  }

  protected goTo(seq: number): void {
    const id = this.runId();
    if (!id) return;
    void this.router.navigate(['/explore', id], {
      queryParams: { event: seq, ...this.harnessParam() },
      replaceUrl: true,
    });
  }

  protected step(step: EventStep): void {
    const seq = stepSeq(this.events(), this.current(), step);
    if (seq !== null) this.goTo(seq);
  }

  /** Jump to the next / previous event that took photos. */
  protected stepPhoto(direction: 'next' | 'previous'): void {
    const seq = stepPhotoSeq(this.events(), this.current(), direction);
    if (seq !== null) this.goTo(seq);
  }

  protected stepRun(delta: 1 | -1): void {
    const target = adjacentRun(this.runList(), this.runId() ?? null, delta);
    if (!target) return;
    const extras = this.harnessQuery();
    void (extras.queryParams
      ? this.router.navigate(['/explore', target.run_id], extras)
      : this.router.navigate(['/explore', target.run_id]));
  }

  /** The version filter lives in the URL; the run and event are kept when it changes. */
  protected setHarness(version: string): void {
    const id = this.runId();
    void this.router.navigate(id ? ['/explore', id] : ['/explore'], {
      queryParams: { harness: version || null },
      queryParamsHandling: 'merge',
    });
  }

  private harnessParam(): { harness?: string } {
    const harness = this.harness();
    return harness ? { harness } : {};
  }

  /** Navigation extras that keep the version filter. */
  private harnessQuery(): { queryParams?: { harness: string } } {
    const harness = this.harness();
    return harness ? { queryParams: { harness } } : {};
  }

  /** The filmstrip: jump to the event that took this photo. */
  protected goToPhoto(index: number): void {
    const e = eventOfPhoto(this.events(), index);
    if (e) this.goTo(e.seq);
  }

  protected onLayerClick(id: string): void {
    const index = photoIndexOfLayer(id);
    if (index !== null) this.goToPhoto(index);
  }

  protected openPhoto(index: number): void {
    const run = this.loadedRun();
    if (!run) return;
    const i = run.photo_list.findIndex((p) => p.index === index);
    void this.viewer.open(run.photo_list.map(toViewerPhoto), Math.max(0, i), run.name);
  }
}

/** What a photo is grouped by in the strip: its sweep, or the stop photos; null for others. */
function groupOf(photo: ExplorationPhoto | undefined): string | null {
  if (!photo) return null;
  if (photo.toward === 'stop_photo') return 'stop';
  return photo.shot > 0 ? `sweep${photo.shot}` : null;
}

function groupTag(photo: ExplorationPhoto): string {
  return photo.toward === 'stop_photo' ? 'Stop photos' : `Sweep ${photo.shot}`;
}
