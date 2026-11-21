import { Injectable, computed, inject, signal } from '@angular/core';
import { forkJoin } from 'rxjs';
import { ApiError } from '../../core/api/api-error';
import { ApiService } from '../../core/api/api.service';
import { Catalog, JudgmentResponse, Pair, Progress } from '../../core/api/api.types';
import { RaterService } from '../../core/services/rater.service';
import { Choice } from './agreement';

export type Phase = 'loading' | 'error' | 'choosing' | 'submitting' | 'revealed' | 'done';
@Injectable()
export class VersusStore {
  private readonly api = inject(ApiService);
  private readonly rater = inject(RaterService);

  readonly phase = signal<Phase>('loading');
  readonly catalog = signal<Catalog | null>(null);
  readonly pair = signal<Pair | null>(null);
  readonly progress = signal<Progress | null>(null);
  readonly result = signal<JudgmentResponse | null>(null);
  readonly choice = signal<Choice | null>(null);
  readonly loadError = signal<ApiError | null>(null);
  readonly notice = signal<string | null>(null);

  readonly canChoose = computed(() => this.phase() === 'choosing');

  private shownAt = 0;
  start(): void {
    this.phase.set('loading');
    this.loadError.set(null);
    forkJoin({ catalog: this.api.catalog(), next: this.api.nextPair() }).subscribe({
      next: ({ catalog, next }) => {
        this.catalog.set(catalog);
        this.showNext(next.pair, next.progress);
      },
      error: (e: ApiError) => this.fail(e),
    });
  }
  choose(choice: Choice): void {
    const pair = this.pair();
    if (!pair || this.phase() !== 'choosing') return;
    const decisionMs = Math.max(0, Math.round(performance.now() - this.shownAt));
    const winner =
      choice === 'skip' ? null : choice === 'left' ? pair.left.stop_id : pair.right.stop_id;
    this.phase.set('submitting');
    this.notice.set(null);
    this.api
      .postJudgment({
        left: pair.left.stop_id,
        right: pair.right.stop_id,
        winner,
        rater: this.rater.payload(),
        decision_ms: decisionMs,
      })
      .subscribe({
        next: (res) => {
          this.choice.set(choice);
          this.result.set(res);
          this.progress.set(res.progress);
          this.phase.set('revealed');
        },
        error: (e: ApiError) => {
          if (e.kind === 'conflict') {
            this.notice.set('That pair was just judged by someone else. Here is a new one.');
            this.loadNext();
          } else {
            this.notice.set(`Could not save your choice: ${e.message}`);
            this.phase.set('choosing');
          }
        },
      });
  }
  next(): void {
    if (this.phase() !== 'revealed') return;
    this.notice.set(null);
    this.loadNext();
  }

  private loadNext(): void {
    this.phase.set('loading');
    this.api.nextPair().subscribe({
      next: (r) => this.showNext(r.pair, r.progress),
      error: (e: ApiError) => this.fail(e),
    });
  }

  private showNext(pair: Pair | null, progress: Progress): void {
    this.progress.set(progress);
    this.result.set(null);
    this.choice.set(null);
    this.pair.set(pair);
    if (pair) {
      this.shownAt = performance.now();
      this.phase.set('choosing');
    } else {
      this.phase.set('done');
    }
  }

  private fail(e: ApiError): void {
    this.loadError.set(e);
    this.phase.set('error');
  }
}
