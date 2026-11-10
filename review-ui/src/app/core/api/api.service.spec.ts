import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { CATALOG, judgmentResponse, nextPair } from '../../testing';
import { ApiError } from './api-error';
import { ApiService } from './api.service';

describe('ApiService', () => {
  let api: ApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('GETs the catalog', () => {
    let result: unknown;
    api.catalog().subscribe((c) => (result = c));
    const req = http.expectOne('/api/catalog');
    expect(req.request.method).toBe('GET');
    req.flush(CATALOG);
    expect(result).toEqual(CATALOG);
  });

  it('GETs stops, one stop (encoded) and the next pair', () => {
    api.stops().subscribe();
    http.expectOne('/api/stops').flush([]);
    api.stop('f 1/2').subscribe();
    http.expectOne('/api/stops/f%201%2F2').flush({});
    api.nextPair().subscribe();
    http.expectOne('/api/pairs/next').flush(nextPair());
  });

  it('POSTs a judgment body as given', () => {
    const body = { left: 'a', right: 'b', winner: null, rater: 'ana', decision_ms: 900 };
    let result: unknown;
    api.postJudgment(body).subscribe((r) => (result = r));
    const req = http.expectOne('/api/judgments');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(body);
    req.flush(judgmentResponse('a', 'b', null), { status: 201, statusText: 'Created' });
    expect(result).toBeTruthy();
  });

  it.each([
    [404, { detail: 'Unknown stop' }, 'not_found', 'Unknown stop'],
    [409, { detail: 'Pair already judged' }, 'conflict', 'Pair already judged'],
    [
      422,
      { detail: [{ msg: 'winner must be left or right' }] },
      'invalid',
      'winner must be left or right',
    ],
    [500, { detail: 'boom' }, 'server', 'boom'],
    [503, 'Service Unavailable', 'server', 'The review server failed'],
  ])('maps status %i to %s', (status, body, kind, message) => {
    let error: unknown;
    api
      .postJudgment({ left: 'a', right: 'b', winner: 'a' })
      .subscribe({ error: (e) => (error = e) });
    http.expectOne('/api/judgments').flush(body, { status, statusText: 'x' });
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).kind).toBe(kind);
    expect((error as ApiError).status).toBe(status);
    expect((error as ApiError).message).toBe(message);
  });

  it('maps a network failure', () => {
    let error: unknown;
    api.catalog().subscribe({ error: (e) => (error = e) });
    http.expectOne('/api/catalog').error(new ProgressEvent('error'));
    expect((error as ApiError).kind).toBe('network');
  });

  it('GETs the explorations list and one run (encoded)', () => {
    api.explorations().subscribe();
    http.expectOne('/api/explorations').flush([]);
    api.explorations('0.6.0').subscribe();
    http.expectOne('/api/explorations?harness=0.6.0').flush([]);
    api.harnessVersions().subscribe();
    http.expectOne('/api/explorations/harness-versions').flush([]);
    api.exploration('f 1/2').subscribe();
    const req = http.expectOne('/api/explorations/f%201%2F2');
    expect(req.request.method).toBe('GET');
    req.flush({});
  });

  it('GETs the shape check and its verdicts', () => {
    api.shapeCheck().subscribe();
    http.expectOne('/api/shape-check').flush({});
    api.shapeVerdicts().subscribe();
    http.expectOne('/api/shape-check/verdicts').flush([]);
  });

  it('PUTs a shape verdict with the body as given', () => {
    const body = { verdict: 'on_route' as const, note: 'ok', rater: 'ana' };
    let result: unknown;
    api.putShapeVerdict('f 1', body).subscribe((r) => (result = r));
    const req = http.expectOne('/api/shape-check/verdicts/f%201');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual(body);
    req.flush({ stop_id: 'f 1', ...body, updated_at: '2026-01-01T00:00:00Z' });
    expect(result).toMatchObject({ stop_id: 'f 1' });
  });

  it('maps a missing shape-check file to the API detail', () => {
    let error: unknown;
    api.shapeCheck().subscribe({ error: (e) => (error = e) });
    http
      .expectOne('/api/shape-check')
      .flush(
        { detail: 'run experiments/explore/shape_check.py' },
        { status: 404, statusText: 'x' },
      );
    expect((error as ApiError).message).toBe('run experiments/explore/shape_check.py');
  });
});
