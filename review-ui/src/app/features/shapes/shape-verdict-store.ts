import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { Observable, catchError, from, lastValueFrom, map, mergeMap, of, toArray } from 'rxjs';
import { ApiService } from '../../core/api/api.service';
import { toApiError } from '../../core/api/api-error';
import { ShapeVerdict, ShapeVerdictValue } from '../../core/api/api.types';
import { RaterService } from '../../core/services/rater.service';
import { planImport } from './shapes-import';

export interface VerdictEntry {
  verdict: ShapeVerdictValue | null;
  note: string;
}

export interface ImportResult {
  imported: number;
  skipped: number;
  failed: number;
}

const EMPTY: VerdictEntry = { verdict: null, note: '' };
export const NOTE_DEBOUNCE_MS = 600;
const IMPORT_CONCURRENCY = 4;

function entryOf(v: ShapeVerdict): VerdictEntry {
  return { verdict: v.verdict, note: v.note };
}

@Injectable()
export class ShapeVerdictStore {
  private readonly api = inject(ApiService);
  private readonly rater = inject(RaterService);

  private readonly _entries = signal<Readonly<Record<string, VerdictEntry>>>({});
  private readonly confirmed = new Map<string, VerdictEntry>();
  private readonly latest = new Map<string, number>();
  private readonly timers = new Map<string, ReturnType<typeof setTimeout>>();
  private requestCounter = 0;

  readonly loaded = signal(false);
  readonly loadError = signal<string | null>(null);
  readonly saveError = signal<{ stopId: string; message: string } | null>(null);
  private readonly _saving = signal<ReadonlySet<string>>(new Set());
  readonly saving = this._saving.asReadonly();

  readonly judged = computed(
    () => Object.values(this._entries()).filter((e) => e.verdict !== null).length,
  );

  constructor() {
    inject(DestroyRef).onDestroy(() => this.flushAll());
  }

  entry(stopId: string): VerdictEntry {
    return this._entries()[stopId] ?? EMPTY;
  }

  load(): void {
    this.loadError.set(null);
    this.api.shapeVerdicts().subscribe({
      next: (list) => {
        const entries: Record<string, VerdictEntry> = {};
        for (const v of list) {
          entries[v.stop_id] = entryOf(v);
          this.confirmed.set(v.stop_id, entryOf(v));
        }
        this._entries.update((current) => ({ ...entries, ...current }));
        this.loaded.set(true);
      },
      error: (e) => this.loadError.set(toApiError(e).message),
    });
  }

  setVerdict(stopId: string, verdict: ShapeVerdictValue): void {
    this.cancelTimer(stopId);
    this.edit(stopId, { ...this.entry(stopId), verdict });
    this.save(stopId);
  }

  setNote(stopId: string, note: string): void {
    this.edit(stopId, { ...this.entry(stopId), note });
    this.cancelTimer(stopId);
    this.timers.set(
      stopId,
      setTimeout(() => {
        this.timers.delete(stopId);
        this.save(stopId);
      }, NOTE_DEBOUNCE_MS),
    );
  }

  flushNote(stopId: string): void {
    if (!this.timers.has(stopId)) return;
    this.cancelTimer(stopId);
    this.save(stopId);
  }

  dismissError(): void {
    this.saveError.set(null);
  }

  async importCsv(csv: string, knownIds: ReadonlySet<string>): Promise<ImportResult> {
    const plan = planImport(csv, knownIds, this.rater.payload());
    const outcomes = await lastValueFrom(
      from(plan.requests).pipe(
        mergeMap(
          (r) =>
            this.api.putShapeVerdict(r.stopId, r.body).pipe(
              map((saved) => ({ ok: true as const, saved })),
              catchError(() => of({ ok: false as const })),
            ),
          IMPORT_CONCURRENCY,
        ),
        toArray(),
      ),
      { defaultValue: [] },
    );
    let imported = 0;
    for (const o of outcomes) {
      if (!o.ok) continue;
      imported++;
      this.confirmed.set(o.saved.stop_id, entryOf(o.saved));
      this._entries.update((cur) => ({ ...cur, [o.saved.stop_id]: entryOf(o.saved) }));
    }
    return { imported, skipped: plan.skipped, failed: outcomes.length - imported };
  }

  private edit(stopId: string, entry: VerdictEntry): void {
    this._entries.update((cur) => ({ ...cur, [stopId]: entry }));
  }

  private save(stopId: string): void {
    const entry = this.entry(stopId);
    const id = ++this.requestCounter;
    this.latest.set(stopId, id);
    this.markSaving(stopId, true);
    this.saveError.set(null);
    const request: Observable<ShapeVerdict> = this.api.putShapeVerdict(stopId, {
      verdict: entry.verdict,
      note: entry.note,
      rater: this.rater.payload(),
    });
    request.subscribe({
      next: (saved) => {
        this.confirmed.set(stopId, entryOf(saved));
        if (this.latest.get(stopId) === id) this.markSaving(stopId, false);
      },
      error: (e) => {
        if (this.latest.get(stopId) !== id) return;
        this.markSaving(stopId, false);
        this.edit(stopId, this.confirmed.get(stopId) ?? EMPTY);
        this.saveError.set({ stopId, message: toApiError(e).message });
      },
    });
  }

  private markSaving(stopId: string, on: boolean): void {
    this._saving.update((cur) => {
      const next = new Set(cur);
      if (on) next.add(stopId);
      else next.delete(stopId);
      return next;
    });
  }

  private cancelTimer(stopId: string): void {
    const t = this.timers.get(stopId);
    if (t !== undefined) clearTimeout(t);
    this.timers.delete(stopId);
  }

  private flushAll(): void {
    for (const stopId of [...this.timers.keys()]) this.flushNote(stopId);
  }
}
