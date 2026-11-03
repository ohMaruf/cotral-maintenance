import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, throwError } from 'rxjs';
import { toApiError } from './api-error';
import {
  Catalog,
  Judgment,
  JudgmentRequest,
  JudgmentResponse,
  NextPairResponse,
  Progress,
  StopDetail,
} from './api.types';

const BASE = '/api';

/** Typed client for the review BFF. Every failure surfaces as an ApiError. */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  catalog(): Observable<Catalog> {
    return this.get<Catalog>('/catalog');
  }

  stops(): Observable<StopDetail[]> {
    return this.get<StopDetail[]>('/stops');
  }

  stop(stopId: string): Observable<StopDetail> {
    return this.get<StopDetail>(`/stops/${encodeURIComponent(stopId)}`);
  }

  nextPair(): Observable<NextPairResponse> {
    return this.get<NextPairResponse>('/pairs/next');
  }

  judgments(): Observable<Judgment[]> {
    return this.get<Judgment[]>('/judgments');
  }

  progress(): Observable<Progress> {
    return this.get<Progress>('/judgments/progress');
  }

  postJudgment(body: JudgmentRequest): Observable<JudgmentResponse> {
    return this.http
      .post<JudgmentResponse>(`${BASE}/judgments`, body)
      .pipe(catchError((e) => throwError(() => toApiError(e))));
  }

  private get<T>(path: string): Observable<T> {
    return this.http
      .get<T>(`${BASE}${path}`)
      .pipe(catchError((e) => throwError(() => toApiError(e))));
  }
}
