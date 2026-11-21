import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, throwError } from 'rxjs';
import { toApiError } from './api-error';
import {
  Catalog,
  Exploration,
  ExplorationSummary,
  HarnessVersion,
  Judgment,
  JudgmentRequest,
  JudgmentResponse,
  NextPairResponse,
  Progress,
  ResultRow,
  RunInfo,
  ShapeCheck,
  ShapeVerdict,
  ShapeVerdictRequest,
  StopDetail,
} from './api.types';

const BASE = '/api';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  catalog(): Observable<Catalog> {
    return this.get<Catalog>('/catalog');
  }

  run(): Observable<RunInfo> {
    return this.get<RunInfo>('/run');
  }

  results(): Observable<ResultRow[]> {
    return this.get<ResultRow[]>('/results');
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

  explorations(harness?: string): Observable<ExplorationSummary[]> {
    const query = harness ? `?harness=${encodeURIComponent(harness)}` : '';
    return this.get<ExplorationSummary[]>(`/explorations${query}`);
  }

  harnessVersions(): Observable<HarnessVersion[]> {
    return this.get<HarnessVersion[]>('/explorations/harness-versions');
  }

  exploration(runId: string): Observable<Exploration> {
    return this.get<Exploration>(`/explorations/${encodeURIComponent(runId)}`);
  }

  shapeCheck(): Observable<ShapeCheck> {
    return this.get<ShapeCheck>('/shape-check');
  }

  shapeVerdicts(): Observable<ShapeVerdict[]> {
    return this.get<ShapeVerdict[]>('/shape-check/verdicts');
  }

  putShapeVerdict(stopId: string, body: ShapeVerdictRequest): Observable<ShapeVerdict> {
    return this.http
      .put<ShapeVerdict>(`${BASE}/shape-check/verdicts/${encodeURIComponent(stopId)}`, body)
      .pipe(catchError((e) => throwError(() => toApiError(e))));
  }

  private get<T>(path: string): Observable<T> {
    return this.http
      .get<T>(`${BASE}${path}`)
      .pipe(catchError((e) => throwError(() => toApiError(e))));
  }
}
