import { RaterField } from '../../shared/rater-field/rater-field';
import { rxResource } from '@angular/core/rxjs-interop';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { ApiError, toApiError } from '../../core/api/api-error';
import { ApiService } from '../../core/api/api.service';
import { ShapeStop, ShapeVerdictValue } from '../../core/api/api.types';
import { ShortcutService } from '../../core/services/shortcut.service';
import { GeoMap } from '../../shared/geo-map/geo-map';
import { OSM_LEGEND, featureCode } from '../../shared/geo-map/osm-features';
import { StateMessage } from '../../shared/state-message/state-message';
import { ShapeVerdictStore } from './shape-verdict-store';
import {
  LayerToggles,
  TOGGLE_LABELS,
  VERDICTS,
  buildShapeLayers,
  distancesToVerified,
  filterByFlag,
  flagLabel,
  flagsPresent,
  loadToggles,
  mapsSearchUrl,
  nearbyFeatures,
  saveToggles,
  routeColor,
  shapeBounds,
  shortName,
  streetViewUrl,
  truthPathText,
  verdictTone,
} from './shapes-layers';

@Component({
  selector: 'app-shapes-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RaterField, GeoMap, RouterLink, StateMessage],
  providers: [ShapeVerdictStore],
  templateUrl: './shapes-page.html',
  styleUrl: './shapes-page.scss',
})
export class ShapesPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  protected readonly store = inject(ShapeVerdictStore);
  readonly stopId = input<string | undefined>();

  protected readonly verdictButtons = VERDICTS;
  protected readonly check = rxResource({ stream: () => this.api.shapeCheck() });
  protected readonly error = computed<ApiError | null>(() =>
    this.check.error() ? toApiError(this.check.error()) : null,
  );

  protected readonly stops = computed(() =>
    this.check.hasValue() ? this.check.value().stops : [],
  );
  protected readonly minOffset = computed(() =>
    this.check.hasValue() ? this.check.value().min_offset_m : 0,
  );

    protected readonly filter = signal<string | null>(null);
  protected readonly filterOptions = computed(() => flagsPresent(this.stops()));
    protected readonly visible = computed(() => filterByFlag(this.stops(), this.filter()));
  protected readonly selected = computed<ShapeStop | null>(() => {
    const stops = this.visible();
    return stops.find((s) => s.id === this.stopId()) ?? stops[0] ?? null;
  });
  protected readonly judgedVisible = computed(
    () => this.visible().filter((s) => this.store.entry(s.id).verdict !== null).length,
  );

  protected readonly toggles = signal<LayerToggles>(loadToggles());
  protected readonly toggleOptions = TOGGLE_LABELS;
  protected readonly osmLegend = OSM_LEGEND;

  protected readonly items = computed(() =>
    this.visible().map((stop) => {
      const verdict = this.store.entry(stop.id).verdict;
      const info = VERDICTS.find((v) => v.value === verdict);
      return {
        stop,
        short: shortName(stop.name),
        metres: Math.round(stop.offset_m),
        flags: stop.flags
          .filter((f) => f !== this.filter())
          .map((f) => flagLabel(f, this.minOffset())),
        verdict: info ? { label: info.short, tone: verdictTone(info.value) } : null,
      };
    }),
  );

  protected readonly layers = computed(() => {
    const s = this.selected();
    return s ? buildShapeLayers(s, this.toggles()) : [];
  });
  protected readonly bounds = computed(() => {
    const s = this.selected();
    return s ? shapeBounds(s) : null;
  });

  protected readonly detail = computed(() => {
    const s = this.selected();
    if (!s) return null;
    return {
      stop: s,
      short: shortName(s.name),
      metres: Math.round(s.offset_m),
      places: distancesToVerified(s).find((x) => x.key === 'P')?.m ?? null,
      flags: s.flags.filter((f) => f !== 'moved').map((f) => flagLabel(f, this.minOffset())),
      features: nearbyFeatures(s),
      routes: s.routes.map((route, i) => ({
        route,
        color: routeColor(i),
        path: truthPathText(route),
      })),
      streetViewV: streetViewUrl(s.truth),
      streetViewG: streetViewUrl(s.gtfs),
      mapsV: mapsSearchUrl(s.truth),
    };
  });
  protected readonly entry = computed(() => {
    const s = this.selected();
    return s ? this.store.entry(s.id) : { verdict: null, note: '' };
  });
  protected readonly saveError = computed(() => {
    const e = this.store.saveError();
    return e && e.stopId === this.selected()?.id ? e.message : null;
  });
  protected readonly saving = computed(() => {
    const s = this.selected();
    return s ? this.store.saving().has(s.id) : false;
  });

  protected readonly importMessage = signal<string | null>(null);
  protected readonly importing = signal(false);

  constructor() {
    this.store.load();
    inject(ShortcutService).listen({
      arrowleft: () => this.move(-1),
      arrowright: () => this.move(1),
      '1': () => this.verdict('on_route'),
      '2': () => this.verdict('off_route'),
      '3': () => this.verdict('unclear'),
    });
    effect(() => {
      const first = this.visible()[0];
      const id = this.stopId();
      if (first && (!id || !this.visible().some((s) => s.id === id))) {
        void this.router.navigate(['/shapes', first.id], { replaceUrl: true });
      }
    });
  }

  protected reload(): void {
    this.check.reload();
  }

  protected flagLabelOf(flag: string): string {
    return flagLabel(flag, this.minOffset());
  }

  protected codeOf(kind: string): string {
    return featureCode(kind);
  }

  protected flagCount(flag: string): number {
    return filterByFlag(this.stops(), flag).length;
  }

  protected setFilter(flag: string | null): void {
    this.filter.set(flag);
  }

  protected toggle(key: keyof LayerToggles): void {
    this.toggles.update((t) => ({ ...t, [key]: !t[key] }));
    saveToggles(this.toggles());
  }

    protected move(delta: 1 | -1): void {
    const stops = this.visible();
    const current = this.selected();
    if (!current || stops.length === 0) return;
    const i = stops.indexOf(current);
    const next = stops[(i + delta + stops.length) % stops.length];
    void this.router.navigate(['/shapes', next.id], { replaceUrl: true });
  }

  protected verdict(value: ShapeVerdictValue): void {
    const s = this.selected();
    if (s) this.store.setVerdict(s.id, value);
  }

  protected onNote(text: string): void {
    const s = this.selected();
    if (s) this.store.setNote(s.id, text);
  }

  protected onNoteBlur(): void {
    const s = this.selected();
    if (s) this.store.flushNote(s.id);
  }

  protected async onImport(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    this.importing.set(true);
    this.importMessage.set(null);
    try {
      const text = await file.text();
      const r = await this.store.importCsv(text, new Set(this.stops().map((s) => s.id)));
      const failed = r.failed > 0 ? `, ${r.failed} failed` : '';
      this.importMessage.set(`Imported ${r.imported}, skipped ${r.skipped}${failed}.`);
    } catch {
      this.importMessage.set('Could not read that file.');
    } finally {
      this.importing.set(false);
    }
  }
}
