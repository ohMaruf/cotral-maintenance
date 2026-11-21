import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RaterService } from '../../core/services/rater.service';
import { osmFeature, route, shapeCheck, shapeStop, verdict } from './shapes-testing';
import { NOTE_DEBOUNCE_MS } from './shape-verdict-store';
import { ShapesPage } from './shapes-page';

function press(key: string, target: EventTarget = document.body): void {
  target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
}

describe('ShapesPage', () => {
  let fixture: ComponentFixture<ShapesPage>;
  let http: HttpTestingController;
  let navigate: ReturnType<typeof vi.spyOn>;
  let el: HTMLElement;

  async function settle(): Promise<void> {
    await fixture.whenStable();
    fixture.detectChanges();
  }

  async function open(
    opts: { stopId?: string; verdicts?: unknown[]; check?: unknown } = {},
  ): Promise<void> {
    fixture = TestBed.createComponent(ShapesPage);
    el = fixture.nativeElement;
    if (opts.stopId) fixture.componentRef.setInput('stopId', opts.stopId);
    fixture.detectChanges();
    TestBed.tick();
    await new Promise((r) => setTimeout(r));
    http.expectOne('/api/shape-check').flush(opts.check ?? shapeCheck());
    http.expectOne('/api/shape-check/verdicts').flush(opts.verdicts ?? []);
    await settle();
  }

  const q = (sel: string) => el.querySelector<HTMLElement>(sel);
  const qa = (sel: string) => [...el.querySelectorAll<HTMLElement>(sel)];
  const pressed = () => qa('.verdict').map((b) => b.getAttribute('aria-pressed'));
  const put = (stopId: string): TestRequest =>
    http.expectOne(`/api/shape-check/verdicts/${stopId}`);

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
  });

  afterEach(() => {
    vi.useRealTimers();
    http.verify();
  });

  it('lists the stops in order with the progress line', async () => {
    await open({ stopId: 'b', verdicts: [verdict('a', { verdict: 'off_route' })] });
    expect(qa('.list .stop .stop-plate').map((s) => s.textContent)).toEqual(['a', 'b', 'c']);
    expect(q('.progress')!.textContent!.replace(/\s+/g, ' ').trim()).toBe('3 stops · 1 judged');
    const items = qa('.list .stop');
    expect(items[0].textContent).toContain('off route');
    expect(items[1].getAttribute('aria-current')).toBe('true');
    expect(items[1].textContent).toContain('83 m');
    expect(items[1].textContent).not.toContain('# b');
  });

  it('opens the first stop when none is in the URL', async () => {
    await open();
    expect(navigate).toHaveBeenCalledWith(['/shapes', 'a'], { replaceUrl: true });
  });

  it('shows the stop details, routes and external links', async () => {
    await open({ stopId: 'a' });
    const d = q('.detail')!;
    expect(d.querySelector('h1')!.textContent).toContain('Stop a');
    expect(d.querySelector('h1 .stop-plate')!.textContent).toBe('a');
    const meta = d.textContent!.replace(/\s+/g, ' ');
    expect(meta).toContain('Moved 83 m by the verifier · sign yes');
    expect(meta).toMatch(/Places \d+ m from V/);
    const rows = [...d.querySelectorAll('tbody tr')].map((r) =>
      r.textContent!.replace(/\s+/g, ' ').trim(),
    );
    expect(rows).toEqual(['s1 124.2 m right3.1 m right60.1 m', 's2 34.2 m left3.1 m right60.1 m']);
    const links = [...d.querySelectorAll<HTMLAnchorElement>('.links a')];
    expect(links.map((a) => a.textContent)).toEqual([
      'Street View at V',
      'Street View at G',
      'Maps at V',
    ]);
    expect(links[0].href).toBe(
      'https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=41.9006,12.5004',
    );
    expect(links[2].href).toBe('https://www.google.com/maps/search/?api=1&query=41.9006,12.5004');
    for (const a of links) {
      expect(a.target).toBe('_blank');
      expect(a.rel).toContain('noopener');
    }
  });

  it('draws the routes, pins and neighbours on the map', async () => {
    await open({ stopId: 'a' });
    expect(
      qa('.leaflet-container .geo-marker')
        .map((m) => m.textContent)
        .filter(Boolean),
    ).toEqual(expect.arrayContaining(['G', 'P', 'V', '➤']));
    expect(qa('.leaflet-container .geo-marker.dot')).toHaveLength(1);
  });

  it('shows "?" for an unknown sign and the comments', async () => {
    const check = shapeCheck();
    check.stops[0] = shapeStop('a', { has_sign: '', comments: 'bench only', routes: [] });
    await open({ stopId: 'a', check });
    const text = q('.detail')!.textContent!.replace(/\s+/g, ' ');
    expect(text).toContain('sign ? · bench only');
    expect(text).toContain('No shape for the trips');
  });

  it('shows the API detail when the shape check is missing', async () => {
    fixture = TestBed.createComponent(ShapesPage);
    el = fixture.nativeElement;
    fixture.detectChanges();
    TestBed.tick();
    await new Promise((r) => setTimeout(r));
    http
      .expectOne('/api/shape-check')
      .flush(
        { detail: 'Not found: run experiments/explore/shape_check.py' },
        { status: 404, statusText: 'x' },
      );
    http.expectOne('/api/shape-check/verdicts').flush([]);
    await settle();
    expect(q('[role=alert]')!.textContent).toContain('run experiments/explore/shape_check.py');
  });

  describe('flags, features and layers', () => {
    const mixed = () => {
      const check = shapeCheck(['a', 'b', 'c', 'd']);
      check.stops[0] = shapeStop('a', { flags: ['moved', 'left_of_path'] });
      check.stops[1] = shapeStop('b', { flags: ['on_detour'] });
      check.stops[2] = shapeStop('c', { flags: ['moved'] });
      check.stops[3] = shapeStop('d', { flags: ['weird'] });
      return check;
    };
    const chips = () => qa('.filters .seg');
    const chip = (label: string) =>
      chips().find((c) =>
        c
          .textContent!.replace(/\s+/g, ' ')
          .trim()
          .startsWith(label + ' '),
      )!;
    const listed = () => qa('.list .stop .stop-plate').map((s) => s.textContent);

    it('shows the flags as text in the list and in the detail', async () => {
      await open({ stopId: 'a', check: mixed() });
      expect(qa('.list .stop')[0].querySelector('.flags')!.textContent).toBe(
        'Moved ≥ 50 m · Left of path',
      );
      expect(qa('.list .stop')[3].textContent).toContain('weird');
      expect(q('.flag-row')!.textContent).toBe('Left of path');
    });

    it('does not repeat the active filter flag on the rows', async () => {
      await open({ stopId: 'a', check: mixed() });
      chip('Moved ≥ 50 m').click();
      fixture.detectChanges();
      expect(qa('.list .stop')[0].querySelector('.flags')!.textContent).toBe('Left of path');
      expect(qa('.list .stop')[1].querySelector('.flags')).toBeNull();
    });

    it('offers All and one toggle per flag present, in contract order', async () => {
      await open({ stopId: 'a', check: mixed() });
      expect(chips().map((c) => c.textContent!.replace(/\s+/g, ' ').trim())).toEqual([
        'All 4',
        'Moved ≥ 50 m 2',
        'Left of path 1',
        'On a detour 1',
        'weird 1',
      ]);
      expect(chips().map((c) => c.getAttribute('aria-pressed'))).toEqual([
        'true',
        'false',
        'false',
        'false',
        'false',
      ]);
    });

    it('filters the list and counts the filtered stops', async () => {
      await open({ stopId: 'a', check: mixed(), verdicts: [verdict('b'), verdict('c')] });
      const progress = () => q('.progress')!.textContent!.replace(/\s+/g, ' ').trim();
      expect(progress()).toBe('4 stops · 2 judged');
      chip('Moved ≥ 50 m').click();
      fixture.detectChanges();
      expect(listed()).toEqual(['a', 'c']);
      expect(progress()).toBe('2 stops · 1 judged');
      expect(chip('Moved ≥ 50 m').getAttribute('aria-pressed')).toBe('true');
      chip('All').click();
      fixture.detectChanges();
      expect(listed()).toEqual(['a', 'b', 'c', 'd']);
    });

    it('moves previous and next within the filtered list, wrapping', async () => {
      await open({ stopId: 'a', check: mixed() });
      chip('Moved ≥ 50 m').click();
      fixture.detectChanges();
      press('ArrowRight');
      expect(navigate).toHaveBeenLastCalledWith(['/shapes', 'c'], { replaceUrl: true });
      fixture.componentRef.setInput('stopId', 'c');
      fixture.detectChanges();
      press('ArrowRight');
      expect(navigate).toHaveBeenLastCalledWith(['/shapes', 'a'], { replaceUrl: true });
      qa('.nav .btn')[0].click();
      expect(navigate).toHaveBeenLastCalledWith(['/shapes', 'a'], { replaceUrl: true });
    });

    it('opens the first visible stop when the current one is filtered out', async () => {
      await open({ stopId: 'b', check: mixed() });
      navigate.mockClear();
      chip('Moved ≥ 50 m').click();
      fixture.detectChanges();
      TestBed.tick();
      expect(navigate).toHaveBeenCalledWith(['/shapes', 'a'], { replaceUrl: true });
    });

    it('shows "–" in the V → path column without a snapped path', async () => {
      const check = shapeCheck(['a']);
      check.stops[0] = shapeStop('a', {
        routes: [route('s1', { matched: null, truth_path_m: null, truth_path_side: null })],
      });
      await open({ stopId: 'a', check });
      const cells = [...q('.detail tbody tr')!.querySelectorAll('td')].map((c) =>
        c.textContent!.trim(),
      );
      expect(cells[3]).toBe('–');
    });

    it('lists the OSM features within 200 m, nearest first', async () => {
      const check = shapeCheck(['a']);
      check.stops[0] = shapeStop('a', {
        osm_features: [
          osmFeature('n2', { kind: 'platform', lat: 41.9016, lon: 12.5004, ref: 'P2' }),
          osmFeature('n1', { kind: 'bus_stop', name: 'Via Roma' }),
          osmFeature('n3', { kind: 'shelter', lat: 41.95, lon: 12.5004 }),
        ],
      });
      await open({ stopId: 'a', check });
      const items = qa('.detail .features li').map((li) =>
        li.textContent!.replace(/\s+/g, ' ').trim(),
      );
      expect(items).toEqual(['B bus_stop · 0 m · Via Roma', 'L platform · 111 m · P2']);
    });

    it('draws OSM feature pins and honours and persists the layer toggles', async () => {
      localStorage.removeItem('shapes.layers');
      const check = shapeCheck(['a']);
      check.stops[0] = shapeStop('a', { osm_features: [osmFeature('n1')] });
      await open({ stopId: 'a', check });
      expect(qa('.leaflet-container .geo-marker.pin-feature')).toHaveLength(1);
      const boxes = qa('.toggles input') as HTMLInputElement[];
      expect(boxes.map((b) => b.checked)).toEqual([true, true, true]);
      boxes[2].click();
      fixture.detectChanges();
      await settle();
      expect(qa('.leaflet-container .geo-marker.pin-feature')).toHaveLength(0);
      expect(JSON.parse(localStorage.getItem('shapes.layers')!)).toEqual({
        raw: true,
        snapped: true,
        features: false,
      });
      localStorage.removeItem('shapes.layers');
    });
  });

  describe('verdicts', () => {
    it('shows loaded verdicts and notes', async () => {
      await open({ stopId: 'a', verdicts: [verdict('a', { verdict: 'unclear', note: 'hmm' })] });
      expect(pressed()).toEqual(['false', 'false', 'true']);
      expect((q('textarea') as HTMLTextAreaElement).value).toBe('hmm');
    });

    it('saves a verdict click at once with the rater, and updates the list', async () => {
      TestBed.inject(RaterService).set('Ana');
      await open({ stopId: 'a', verdicts: [verdict('a', { verdict: null, note: 'kept' })] });
      qa('.verdict')[0].click();
      const req = put('a');
      expect(req.request.method).toBe('PUT');
      expect(req.request.body).toEqual({ verdict: 'on_route', note: 'kept', rater: 'Ana' });
      fixture.detectChanges();
      expect(pressed()).toEqual(['true', 'false', 'false']);
      expect(q('.progress')!.textContent).toContain('1 judged');
      req.flush(verdict('a', { note: 'kept', rater: 'Ana' }));
      await settle();
      expect(pressed()).toEqual(['true', 'false', 'false']);
      expect(q('.list .stop .verdict-word')!.textContent).toContain('on route');
      expect(q('[role=alert]')).toBeNull();
    });

    it('rolls back and shows the error when the save fails', async () => {
      await open({ stopId: 'a', verdicts: [verdict('a', { verdict: 'unclear' })] });
      qa('.verdict')[1].click();
      fixture.detectChanges();
      expect(pressed()).toEqual(['false', 'true', 'false']);
      put('a').flush({ detail: 'database is locked' }, { status: 500, statusText: 'x' });
      await settle();
      expect(pressed()).toEqual(['false', 'false', 'true']);
      expect(q('.detail [role=alert]')!.textContent).toContain('database is locked');
      expect(q('.progress')!.textContent).toContain('1 judged');
    });

    it('rolls back to nothing when a first save fails', async () => {
      await open({ stopId: 'a' });
      qa('.verdict')[0].click();
      put('a').error(new ProgressEvent('error'));
      await settle();
      expect(pressed()).toEqual(['false', 'false', 'false']);
      expect(q('.detail [role=alert]')!.textContent).toContain('Cannot reach the review server');
    });

    it('sets the verdict with the 1, 2 and 3 keys', async () => {
      await open({ stopId: 'a' });
      press('2');
      expect(put('a').request.body.verdict).toBe('off_route');
      press('3');
      const reqs = http.match('/api/shape-check/verdicts/a');
      expect(reqs).toHaveLength(1);
      expect(reqs[0].request.body.verdict).toBe('unclear');
      reqs[0].flush(verdict('a', { verdict: 'unclear' }));
      press('1');
      expect(put('a').request.body.verdict).toBe('on_route');
    });

    it('does not treat 1/2/3 or the arrows as shortcuts while typing a note', async () => {
      await open({ stopId: 'a' });
      const area = q('textarea')!;
      press('1', area);
      press('ArrowRight', area);
      expect(navigate).not.toHaveBeenCalledWith(['/shapes', 'b'], expect.anything());
      http.expectNone('/api/shape-check/verdicts/a');
    });

    it('saves a note after a pause while typing, once', async () => {
      await open({ stopId: 'a' });
      vi.useFakeTimers();
      const area = q('textarea') as HTMLTextAreaElement;
      area.value = 'on the';
      area.dispatchEvent(new Event('input'));
      vi.advanceTimersByTime(NOTE_DEBOUNCE_MS - 100);
      area.value = 'on the other side';
      area.dispatchEvent(new Event('input'));
      vi.advanceTimersByTime(NOTE_DEBOUNCE_MS - 100);
      http.expectNone('/api/shape-check/verdicts/a');
      vi.advanceTimersByTime(200);
      const req = put('a');
      expect(req.request.body).toMatchObject({ verdict: null, note: 'on the other side' });
      req.flush(verdict('a', { verdict: null, note: 'on the other side' }));
    });

    it('saves a note on blur right away and not again after the pause', async () => {
      await open({ stopId: 'a', verdicts: [verdict('a', { verdict: 'on_route' })] });
      vi.useFakeTimers();
      const area = q('textarea') as HTMLTextAreaElement;
      area.value = 'checked';
      area.dispatchEvent(new Event('input'));
      area.dispatchEvent(new Event('blur'));
      const req = put('a');
      expect(req.request.body).toMatchObject({ verdict: 'on_route', note: 'checked' });
      req.flush(verdict('a', { note: 'checked' }));
      vi.advanceTimersByTime(NOTE_DEBOUNCE_MS * 2);
      http.expectNone('/api/shape-check/verdicts/a');
    });

    it('does not roll back an older failed save over a newer one', async () => {
      await open({ stopId: 'a' });
      qa('.verdict')[0].click();
      const first = put('a');
      qa('.verdict')[1].click();
      const second = put('a');
      first.flush({ detail: 'x' }, { status: 500, statusText: 'x' });
      second.flush(verdict('a', { verdict: 'off_route' }));
      await settle();
      expect(pressed()).toEqual(['false', 'true', 'false']);
      expect(q('.detail [role=alert]')).toBeNull();
    });

    it('warns when the saved verdicts cannot be loaded', async () => {
      fixture = TestBed.createComponent(ShapesPage);
      el = fixture.nativeElement;
      fixture.detectChanges();
      TestBed.tick();
      await new Promise((r) => setTimeout(r));
      http.expectOne('/api/shape-check').flush(shapeCheck());
      http
        .expectOne('/api/shape-check/verdicts')
        .flush({ detail: 'nope' }, { status: 500, statusText: 'x' });
      await settle();
      expect(q('.list .warn')!.textContent).toContain('nope');
    });
  });

  describe('navigation', () => {
    it('moves with the arrow keys and the buttons, wrapping around', async () => {
      await open({ stopId: 'c' });
      press('ArrowRight');
      expect(navigate).toHaveBeenLastCalledWith(['/shapes', 'a'], { replaceUrl: true });
      press('ArrowLeft');
      expect(navigate).toHaveBeenLastCalledWith(['/shapes', 'b'], { replaceUrl: true });
      const [prev, next] = qa('.nav .btn');
      prev.click();
      expect(navigate).toHaveBeenLastCalledWith(['/shapes', 'b'], { replaceUrl: true });
      next.click();
      expect(navigate).toHaveBeenLastCalledWith(['/shapes', 'a'], { replaceUrl: true });
    });
  });

  describe('export and import', () => {
    it('links to the CSV export', async () => {
      await open({ stopId: 'a' });
      const link = q('.io a')!;
      expect(link.getAttribute('href')).toBe('/api/shape-check/verdicts.csv');
      expect(link.textContent).toContain('Export CSV');
    });

    async function importFile(csv: string): Promise<void> {
      const input = q('input[type=file]') as HTMLInputElement;
      const file = new File([csv], 'old.csv', { type: 'text/csv' });
      Object.defineProperty(input, 'files', { value: [file], configurable: true });
      input.dispatchEvent(new Event('change'));
      await vi.waitFor(() => expect(http.match(() => false)).toBeDefined());
      await new Promise((r) => setTimeout(r, 20));
    }

    it('PUTs each row with a verdict or note for a known stop and reports the counts', async () => {
      TestBed.inject(RaterService).set('Ana');
      await open({ stopId: 'a' });
      const csv = [
        'stop_id,offset_m,verdict,note,closest_shape_m,has_osm',
        'a,83.2,on_route,"near, the ""bus"" bay",4.1,1',
        'b,60,,,12,0',
        'c,51,unclear,,3,0',
        'zzz,50,on_route,,1,0',
      ].join('\n');
      await importFile(csv);
      const reqs = http.match((r) => r.url.startsWith('/api/shape-check/verdicts/'));
      expect(reqs.map((r) => r.request.url)).toEqual([
        '/api/shape-check/verdicts/a',
        '/api/shape-check/verdicts/c',
      ]);
      expect(reqs[0].request.method).toBe('PUT');
      expect(reqs[0].request.body).toEqual({
        verdict: 'on_route',
        note: 'near, the "bus" bay',
        rater: 'Ana',
      });
      reqs[0].flush(verdict('a', { note: 'near, the "bus" bay' }));
      reqs[1].flush({ detail: 'locked' }, { status: 500, statusText: 'x' });
      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(q('.note-msg')!.textContent).toBe('Imported 1, skipped 2, 1 failed.');
      });
      expect(q('.progress')!.textContent).toContain('1 judged');
      expect(pressed()).toEqual(['true', 'false', 'false']);
    });

    it('reports an import with nothing to do', async () => {
      await open({ stopId: 'a' });
      await importFile('stop_id,offset_m,verdict,note,closest_shape_m,has_osm\nb,1,,,1,0\n');
      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(q('.note-msg')!.textContent).toBe('Imported 0, skipped 1.');
      });
    });
  });
});
