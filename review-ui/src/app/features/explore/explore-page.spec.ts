import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { Exploration } from '../../core/api/api.types';
import { PhotoViewerService } from '../photo-viewer/photo-viewer.service';
import {
  event,
  exploration,
  summary,
  imagesExploration,
  sweepExploration,
  harness,
  photo,
} from './explore-testing';
import { ExplorePage } from './explore-page';

function press(key: string): void {
  document.body.dispatchEvent(
    new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }),
  );
}

describe('ExplorePage', () => {
  let fixture: ComponentFixture<ExplorePage>;
  let http: HttpTestingController;
  let navigate: ReturnType<typeof vi.spyOn>;
  let el: HTMLElement;

  const runs = [
    summary('f1'),
    summary('f2', { outcome: 'weird_outcome' }),
    summary('f3', { outcome: 'no_imagery', err_found_m: null, photos: 0, budget_used: 0 }),
  ];

  async function settle(): Promise<void> {
    await fixture.whenStable();
    fixture.detectChanges();
  }

  async function open(
    opts: {
      runId?: string;
      event?: string;
      run?: Exploration;
      runs?: unknown;
      harness?: string;
    } = {},
  ): Promise<void> {
    fixture = TestBed.createComponent(ExplorePage);
    el = fixture.nativeElement;
    if (opts.runId) fixture.componentRef.setInput('runId', opts.runId);
    if (opts.event) fixture.componentRef.setInput('event', opts.event);
    if (opts.harness) fixture.componentRef.setInput('harness', opts.harness);
    fixture.detectChanges();
    TestBed.tick();
    await new Promise((r) => setTimeout(r));
    http.expectOne('/api/explorations').flush(opts.runs ?? runs);
    if (opts.runId) {
      http.expectOne(`/api/explorations/${opts.runId}`).flush(opts.run ?? exploration(opts.runId));
    }
    await settle();
  }

  const q = (sel: string) => el.querySelector<HTMLElement>(sel);
  const qa = (sel: string) => [...el.querySelectorAll<HTMLElement>(sel)];
  const steps = () => qa('.timeline .step');
  const currentSeq = () =>
    steps().find((s) => s.getAttribute('aria-current') === 'step')?.dataset['seq'];

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
  });

  afterEach(() => {
    TestBed.inject(Dialog).closeAll();
    http.verify();
  });

  it('lists the runs with outcome badges, photos, errors, model and the selection', async () => {
    await open({ runId: 'f2' });
    const items = qa('app-run-list .run');
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toContain('Found');
    expect(items[0].textContent).toContain('f1');
    expect(items[0].textContent).toContain('Stop f1');
    expect(items[0].textContent).toContain('3/14 photos');
    expect(items[0].textContent).toContain('40.0 m → 6.5 m');
    expect(items[0].textContent).toContain('claude-haiku-5-5');
    expect(items[1].textContent).toContain('weird outcome');
    expect(items[2].textContent).toContain('No imagery');
    expect(items[2].textContent).toContain('0/14 photos');
    expect(items[2].textContent).toContain('40.0 m → –');
    expect(items[1].getAttribute('aria-current')).toBe('true');
    expect(items[0].getAttribute('aria-current')).toBeNull();
  });

  it('opens the first run when none is in the URL', async () => {
    await open();
    expect(navigate).toHaveBeenCalledWith(['/explore', 'f1'], { replaceUrl: true });
  });

  it('shows the run header with outcome, reason, errors, times and the searched stretch', async () => {
    await open({
      runId: 'f1',
      run: exploration('f1', { outcome: 'not_found', outcome_reason: 'photo budget used' }),
    });
    const head = q('app-run-header')!.textContent!;
    expect(head).toContain('Stop f1');
    expect(head).toContain('Not found');
    expect(head).toContain('photo budget used');
    expect(head).toContain('claude-haiku-5-5');
    expect(head).toContain('3/14 photos');
    expect(head).toContain('40.0 m');
    expect(head).toContain('6.5 m');
    expect(head).toContain('2 min 30 s');
    expect(head).toContain('-400 m … 400 m along the path');
  });

  it("shows the model's report, open when short and collapsed when long", async () => {
    await open({ runId: 'f1' });
    const report = () => q('app-run-header details.report') as HTMLDetailsElement;
    expect(report().textContent).toContain('I found the stop.');
    expect(report().open).toBe(true);
    await open({ runId: 'f1', run: exploration('f1', { report: 'x'.repeat(900) }) });
    expect(report().open).toBe(false);
    await open({ runId: 'f1', run: exploration('f1', { report: null }) });
    expect(report()).toBeNull();
  });

  it('shows a stop that was never searched with its reason, turns and no report', async () => {
    await open({
      runId: 'f3',
      run: exploration('f3', {
        outcome: 'no_imagery',
        outcome_reason: 'no Street View from 2024 on along the path',
        turns: 0,
        report: null,
        err_found_m: null,
        photo_list: [],
        event_list: [],
        path: [],
        candidates: [],
      }),
    });
    const head = q('app-run-header')!.textContent!.replace(/\s+/g, ' ');
    expect(head).toContain('No imagery');
    expect(head).toContain('no Street View from 2024 on along the path');
    expect(head).toContain('Turns0');
    expect(q('app-run-header details.report')).toBeNull();
  });

  it('lists every event in exact seq order with its kind, summary and budget', async () => {
    const shuffled = exploration('f1');
    shuffled.event_list = [...shuffled.event_list].reverse();
    await open({ runId: 'f1', run: shuffled });
    expect(steps().map((s) => s.dataset['seq'])).toEqual(['1', '2', '3', '4', '5', '6']);
    expect(currentSeq()).toBe('1');
    const text = (i: number) => steps()[i].textContent!.replace(/\s+/g, ' ');
    expect(text(0)).toContain('begin');
    expect(text(0)).toContain('2/14');
    expect(text(2)).toContain('look');
    expect(text(2)).toContain('PHOTO 3: from the panorama at +5 m');
    expect(text(2)).toContain('3/14');
    expect(text(5)).toContain('Something new');
  });

  it("styles thoughts as the model's words and refused calls as errors", async () => {
    await open({ runId: 'f1' });
    const thought = steps()[1];
    expect(thought.classList.contains('thought')).toBe(true);
    expect(thought.querySelector('q')!.textContent).toBe('I will look ahead.');
    expect(thought.querySelector('.tool')).toBeNull();
    const refused = steps()[3];
    expect(refused.classList.contains('danger')).toBe(true);
    expect(refused.textContent).toContain('ERROR: photo must be an integer');
    expect(refused.querySelector('.tool')).toBeNull();
    expect(steps()[2].classList.contains('danger')).toBe(false);
    expect(steps()[2].classList.contains('photo-step')).toBe(true);
    expect(steps()[1].classList.contains('photo-step')).toBe(false);
  });

  it('marks a recorded tool error as a danger row, keeping the tool name', async () => {
    const run = exploration('f1');
    run.event_list[2] = event(3, {
      kind: 'look',
      summary: 'ERROR: no panorama within 25 m',
      error: 'no panorama within 25 m',
      photos_used: 2,
    });
    await open({ runId: 'f1', run });
    expect(steps()[2].classList.contains('danger')).toBe(true);
    expect(steps()[2].querySelector('.tool')!.textContent).toBe('look');
  });

  it('selects the event from the ?event param and falls back for unknown values', async () => {
    await open({ runId: 'f1', event: '4' });
    expect(currentSeq()).toBe('4');
    expect(q('app-event-detail')!.textContent).toContain('#4');
    fixture.componentRef.setInput('event', '99');
    await settle();
    expect(currentSeq()).toBe('1');
  });

  it('puts the event in the URL when a step is clicked', async () => {
    await open({ runId: 'f1' });
    steps()[2].click();
    expect(navigate).toHaveBeenCalledWith(['/explore', 'f1'], {
      queryParams: { event: 3 },
      replaceUrl: true,
    });
  });

  it('moves with the arrow keys, Home and End, never past the ends', async () => {
    await open({ runId: 'f1', event: '2' });
    press('ArrowRight');
    expect(navigate).toHaveBeenLastCalledWith(
      ['/explore', 'f1'],
      expect.objectContaining({ queryParams: { event: 3 } }),
    );
    press('ArrowLeft');
    expect(navigate).toHaveBeenLastCalledWith(
      ['/explore', 'f1'],
      expect.objectContaining({ queryParams: { event: 1 } }),
    );
    press('End');
    expect(navigate).toHaveBeenLastCalledWith(
      ['/explore', 'f1'],
      expect.objectContaining({ queryParams: { event: 6 } }),
    );
    press('Home');
    expect(navigate).toHaveBeenLastCalledWith(
      ['/explore', 'f1'],
      expect.objectContaining({ queryParams: { event: 1 } }),
    );

    navigate.mockClear();
    fixture.componentRef.setInput('event', '1');
    await settle();
    press('ArrowLeft');
    press('Home');
    expect(navigate).not.toHaveBeenCalled();
  });

  it('jumps to the next and previous event with photos with . and ,', async () => {
    await open({ runId: 'f1', event: '2' });
    press('.');
    expect(navigate).toHaveBeenLastCalledWith(
      ['/explore', 'f1'],
      expect.objectContaining({ queryParams: { event: 3 } }),
    );
    press(',');
    expect(navigate).toHaveBeenLastCalledWith(
      ['/explore', 'f1'],
      expect.objectContaining({ queryParams: { event: 1 } }),
    );
    navigate.mockClear();
    fixture.componentRef.setInput('event', '1');
    await settle();
    press(',');
    expect(navigate).not.toHaveBeenCalled();
    fixture.componentRef.setInput('event', '6');
    await settle();
    press('.');
    expect(navigate).not.toHaveBeenCalled();
    expect(q('.hint')!.textContent).toContain('previous / next photo');
  });

  it('moves between runs with [ and ], dropping the event', async () => {
    await open({ runId: 'f2', event: '3' });
    press(']');
    expect(navigate).toHaveBeenLastCalledWith(['/explore', 'f3']);
    press('[');
    expect(navigate).toHaveBeenLastCalledWith(['/explore', 'f1']);
  });

  it('ignores shortcuts while typing in a field', async () => {
    await open({ runId: 'f1', event: '2' });
    const input = document.createElement('input');
    document.body.append(input);
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    input.remove();
    expect(navigate).not.toHaveBeenCalled();
  });

  it('shows the photos of a tool event large with their facts and the copyright', async () => {
    await open({ runId: 'f1', event: '3' });
    const d = q('app-event-detail')!;
    expect(d.querySelectorAll('.photo-block')).toHaveLength(1);
    expect(d.querySelector('img')?.getAttribute('src')).toBe('/api/explorations/f1/photos/p3.jpg');
    const text = d.textContent!;
    for (const part of [
      'look',
      'pano3',
      'Jun 2025',
      '100°',
      '24.0 m',
      '2.0 m',
      'across',
      'Opening photo',
      '© Google',
      '3/14 photos used',
    ]) {
      expect(text).toContain(part);
    }
  });

  it('shows both opening photos of begin', async () => {
    await open({ runId: 'f1', event: '1' });
    const d = q('app-event-detail')!;
    expect(d.querySelectorAll('.photo-block img')).toHaveLength(2);
    expect(d.textContent).toContain('yes (before the first turn)');
  });

  it('shows a tool call with its arguments as key/value rows and the full result', async () => {
    await open({ runId: 'f1', event: '3' });
    const d = q('app-event-detail')!;
    const rows = [...d.querySelectorAll('.args > div')].map((r) =>
      r.textContent!.replace(/\s+/g, ' ').trim(),
    );
    expect(rows).toEqual(['from_m5', 'towardforward']); // the null argument is left out
    const result = d.querySelector<HTMLElement>('pre.result')!;
    expect(result.textContent).toBe('PHOTO 3: from the panorama at +5 m\nsecond line');
  });

  it('shows a thought with its full text and no tool sections', async () => {
    const run = exploration('f1');
    const text = 'First line.\nSecond line, much longer than a timeline row would show. '.repeat(3);
    run.event_list[1] = event(2, {
      kind: 'thought',
      summary: text,
      photos_used: 2,
      raw: { request: null, response: text },
    });
    await open({ runId: 'f1', event: '2', run });
    const d = q('app-event-detail')!;
    expect(d.querySelector('blockquote.thought')!.textContent).toBe(text);
    expect(d.querySelector('.args')).toBeNull();
    expect(d.querySelector('pre.result')).toBeNull();
    expect(d.querySelector('.photo-block')).toBeNull();
  });

  it('shows a refused call in the danger colour with its error', async () => {
    await open({ runId: 'f1', event: '4' });
    const d = q('app-event-detail')!;
    expect(d.querySelector('h2')!.classList.contains('danger')).toBe(true);
    expect(d.textContent).toContain('Refused call');
    expect(d.querySelector('pre.result.danger-box')!.textContent).toBe('photo must be an integer');
    expect(d.querySelector('.args')!.textContent).toContain('mcp__explorer__mark_clear');
  });

  it("shows the candidate's checklist as a yes/no/unsure grid, yes first", async () => {
    await open({ runId: 'f1', event: '5' });
    const d = q('app-event-detail')!;
    expect([...d.querySelectorAll('.checklist thead th')].map((h) => h.textContent)).toEqual([
      'Feature',
      'yes',
      'no',
      'unsure',
    ]);
    const rows = [...d.querySelectorAll('.checklist tbody tr')];
    expect(rows.map((r) => r.querySelector('th')!.textContent)).toEqual([
      'cotral_logo',
      'plate',
      'shelter',
      'timetable',
    ]);
    const marked = (r: Element) =>
      [...r.querySelectorAll('td')].map((td) => td.classList.contains('on'));
    expect(marked(rows[0])).toEqual([true, false, false]);
    expect(marked(rows[1])).toEqual([false, false, true]);
    expect(marked(rows[2])).toEqual([false, true, false]);
    expect(d.textContent).toContain('Checklist of candidate 1');
  });

  it('shows no checklist for other kinds or an unknown candidate', async () => {
    await open({ runId: 'f1', event: '3' });
    expect(q('app-event-detail .checklist')).toBeNull();
    const run = exploration('f1');
    run.event_list[4] = event(5, {
      kind: 'answer_checklist',
      photos_used: 3,
      raw: { request: { candidate: 9 }, response: 'x' },
    });
    await open({ runId: 'f1', event: '5', run });
    expect(q('app-event-detail .checklist')).toBeNull();
  });

  describe('a sweep run', () => {
    const sweepRuns = [
      summary('n1', { budget_unit: 'sweeps', budget_used: 1, budget_max: 12, max_photos: 12 }),
    ];

    it('shows the budget with its unit in the list, the header and the events', async () => {
      await open({ runId: 'n1', runs: sweepRuns, run: sweepExploration() });
      expect(q('app-run-list')!.textContent).toContain('1/12 sweeps');
      expect(q('app-run-header')!.textContent).toContain('1/12 sweeps');
      expect(steps()[0].textContent!.replace(/\s+/g, ' ')).toContain('1/12');
      expect(q('app-event-detail')!.textContent).toContain('1/12 sweeps used');
    });

    it('groups the two photos of a sweep and words each photo', async () => {
      await open({ runId: 'n1', runs: sweepRuns, run: sweepExploration() });
      const items = qa('.film li');
      expect(items.map((li) => li.classList.contains('group-start'))).toEqual([
        true,
        false,
        false,
        false,
      ]);
      expect(items.map((li) => li.classList.contains('group-end'))).toEqual([
        false,
        true,
        false,
        false,
      ]);
      expect(items[0].querySelector('.group-tag')!.textContent).toContain('Sweep 1');
      const captions = items.map((li) =>
        li.querySelector('.cap')!.textContent!.replace(/\s+/g, ' '),
      );
      expect(captions[0]).toContain('sweep ahead-right');
      expect(captions[1]).toContain('sweep behind-right');
      expect(captions[2]).toContain('zoom ×8 of photo 1');
      expect(captions[3]).toContain('confirm');
    });

    it("shows the confirmer's note and checklist on confirm", async () => {
      await open({ runId: 'n1', event: '3', runs: sweepRuns, run: sweepExploration() });
      const d = q('app-event-detail')!;
      expect(d.textContent).toContain('A blue Cotral pole.');
      expect(d.textContent).toContain('Checklist of candidate 1');
      expect(d.querySelectorAll('.checklist tbody tr')).toHaveLength(4);
      const open_ = vi.spyOn(TestBed.inject(PhotoViewerService), 'open').mockResolvedValue();
      d.querySelector<HTMLElement>('.confirmer-note .link')!.click();
      expect(open_).toHaveBeenCalledTimes(1);
      expect(open_.mock.calls[0][1]).toBe(3);
    });

    it('fades the map by photos taken, not by sweeps', async () => {
      await open({ runId: 'n1', event: '2', runs: sweepRuns, run: sweepExploration() });
      const frames = qa('.film .frame');
      expect(frames.map((f) => f.classList.contains('later'))).toEqual([false, false, false, true]);
    });
  });

  describe('harness versions', () => {
    const versioned = [
      summary('u1'),
      summary('a1', { harness: harness('0.6.0') }),
      summary('b1', { harness: harness('0.7.0'), outcome: 'not_found' }),
      summary('a2', { harness: harness('0.6.0'), outcome: 'error' }),
    ];

    it('groups runs newest version first with counts and found/total, groups collapse', async () => {
      await open({ runId: 'a1', runs: versioned });
      const heads = qa('.group-head .toggle').map((b) =>
        b.textContent!.replace(/\s+/g, ' ').trim(),
      );
      expect(heads).toEqual([
        expect.stringContaining('v0.7.01 run · 0/1 found'),
        expect.stringContaining('v0.6.02 runs · 1/2 found'),
        expect.stringContaining('unversioned1 run · 1/1 found'),
      ]);
      expect(qa('app-run-list .run').map((a) => a.querySelector('.id')!.textContent)).toEqual([
        'b1',
        'a1',
        'a2',
        'u1',
      ]);
      qa('.group-head .toggle')[1].click();
      fixture.detectChanges();
      expect(qa('app-run-list .run')).toHaveLength(2);
      expect(qa('.group-head .toggle')[1].getAttribute('aria-expanded')).toBe('false');
    });

    it('filters by the harness query param and keeps it when moving between runs', async () => {
      await open({ runId: 'a1', runs: versioned, harness: '0.6.0' });
      expect(qa('app-run-list .run').map((a) => a.querySelector('.id')!.textContent)).toEqual([
        'a1',
        'a2',
      ]);
      press(']');
      expect(navigate).toHaveBeenLastCalledWith(['/explore', 'a2'], {
        queryParams: { harness: '0.6.0' },
      });
      press('ArrowRight');
      expect(navigate).toHaveBeenLastCalledWith(['/explore', 'a1'], {
        queryParams: { event: 2, harness: '0.6.0' },
        replaceUrl: true,
      });
    });

    it('changes the filter through the URL', async () => {
      await open({ runId: 'a1', runs: versioned });
      const select = q('.filter select') as HTMLSelectElement;
      expect([...select.options].map((o) => o.value)).toEqual([
        '',
        '0.7.0',
        '0.6.0',
        'unversioned',
      ]);
      select.value = '0.7.0';
      select.dispatchEvent(new Event('change'));
      expect(navigate).toHaveBeenLastCalledWith(['/explore', 'a1'], {
        queryParams: { harness: '0.7.0' },
        queryParamsHandling: 'merge',
      });
    });

    it('says so when no run has the filtered version', async () => {
      await open({ runs: versioned, harness: '9.9' });
      expect(qa('app-run-list .run')).toHaveLength(0);
      expect(el.textContent).toContain('No runs of this harness version');
    });

    it('shows the harness, billing, tiles, start kind and tile photos of a 0.6 run', async () => {
      const run = exploration('a1', {
        harness: harness('0.6.0'),
        billed_static: 3,
        billed_tiles: 10,
        tiles_used: 12,
        tiles_max: 42,
        start_kind: 'osm_ref',
        photo_list: [
          photo(1, { toward: 'aimed', opening: true }),
          photo(2, { toward: 'look_from', opening: false, source: 'tiles', tiles: 8 }),
        ],
        event_list: [
          event(1, { kind: 'begin', photos: [1], photos_used: 1 }),
          event(2, { kind: 'look_from', photos: [2], photos_used: 2 }),
        ],
      });
      await open({ runId: 'a1', runs: versioned, run });
      const header = q('app-run-header')!.textContent!.replace(/\s+/g, ' ');
      expect(header).toContain('v0.6.0');
      expect(header).toContain('da028ea');
      expect(header).toContain('dirty');
      expect(header).toContain('haiku');
      expect(header).toContain('Billed3 Static, 10 tiles');
      expect(header).toContain('12/42 tiles');
      expect(header).toContain('StartOSM by ref');
      const frames = qa('.film .frame').map((f) => f.textContent!.replace(/\s+/g, ' '));
      expect(frames[0]).toContain('opening, aimed at the start');
      expect(frames[0]).not.toContain('tiles');
      expect(frames[1]).toContain('look from another panorama');
      expect(frames[1]).toContain('tiles');
      expect(qa('.timeline .step')[1].textContent).toContain('look_from');
    });

    it('marks no harness details on an unversioned run', async () => {
      await open({ runId: 'f1' });
      const header = q('app-run-header')!.textContent!;
      expect(header).toContain('unversioned');
      expect(header).not.toContain('dirty');
    });
  });

  describe('an images run', () => {
    const imageRuns = [
      summary('i1', { budget_unit: 'images', budget_used: 3, budget_max: 12, billed_used: 4 }),
    ];

    it('shows the images budget and what was billed', async () => {
      await open({ runId: 'i1', runs: imageRuns, run: imagesExploration() });
      expect(q('app-run-list')!.textContent).toContain('3/12 images');
      const header = q('app-run-header')!.textContent!.replace(/\s+/g, ' ');
      expect(header).toContain('3/12 images, 1 zooms, 1 confirmations');
      expect(header).toContain('Billed0 Static, 0 tiles');
      expect(q('app-event-detail')!.textContent).toContain('/12 images used');
    });

    it('shows single-photo sweeps as groups of one and the stop photos as a group', async () => {
      await open({ runId: 'i1', runs: imageRuns, run: imagesExploration() });
      const items = qa('.film li');
      expect(items.map((li) => li.classList.contains('group-start'))).toEqual([
        true,
        true,
        false,
        true,
        false,
      ]);
      expect(items.map((li) => li.classList.contains('group-end'))).toEqual([
        true,
        true,
        false,
        false,
        true,
      ]);
      expect(items.map((li) => li.querySelector('.group-tag')?.textContent?.trim())).toEqual([
        'Sweep 1',
        'Sweep 2',
        undefined,
        'Stop photos',
        undefined,
      ]);
      const captions = items.map((li) =>
        li.querySelector('.cap')!.textContent!.replace(/\s+/g, ' '),
      );
      expect(captions[0]).toContain('sweep ahead-right');
      expect(captions[1]).toContain('sweep behind-right');
      expect(captions[3]).toContain('stop photo');
    });

    it('shows the stop photos prominently and opens one in the viewer', async () => {
      await open({ runId: 'i1', runs: imageRuns, run: imagesExploration() });
      const section = q('.stop-photos')!;
      expect(section.querySelectorAll('.stop-photo')).toHaveLength(2);
      const open_ = vi.spyOn(TestBed.inject(PhotoViewerService), 'open').mockResolvedValue();
      section.querySelector<HTMLElement>('.stop-photo')!.click();
      expect(open_).toHaveBeenCalledTimes(1);
      expect(open_.mock.calls[0][1]).toBe(3);
    });

    it('has no stop photos section for runs without any', async () => {
      await open({ runId: 'n1', run: sweepExploration() });
      expect(q('.stop-photos')).toBeNull();
    });
  });

  it('shows no checklist for the confirm of an old run', async () => {
    const run = exploration('f1');
    run.event_list[4] = event(5, {
      kind: 'confirm',
      photos_used: 3,
      raw: { request: { candidate: 2 }, response: 'x' },
    });
    await open({ runId: 'f1', event: '5', run });
    expect(q('app-event-detail .checklist')).toBeNull();
  });

  it('opens the photo full size from the detail', async () => {
    await open({ runId: 'f1', event: '3' });
    const open_ = vi.spyOn(TestBed.inject(PhotoViewerService), 'open').mockResolvedValue();
    q('app-event-detail .photo-btn')!.click();
    expect(open_).toHaveBeenCalledTimes(1);
    const [photos, index, name] = open_.mock.calls[0];
    expect(photos).toHaveLength(3);
    expect(index).toBe(2);
    expect(name).toBe('Stop f1');
    expect(photos[2].url).toBe('/api/explorations/f1/photos/p3.jpg');
  });

  it('renders an unknown event kind generically, with raw JSON on demand', async () => {
    await open({ runId: 'f1', event: '6' });
    const d = q('app-event-detail')!;
    expect(d.textContent).toContain('#6');
    expect(d.textContent).toContain('mystery');
    expect(d.textContent).toContain('Something new');
    expect(d.querySelector('.photo-block')).toBeNull();
    expect(steps()[5].textContent).toContain('Something new');

    expect(d.querySelector('details pre')).toBeNull();
    const [request, response] = [...d.querySelectorAll<HTMLDetailsElement>('details.raw')];
    request.open = true;
    request.dispatchEvent(new Event('toggle'));
    response.open = true;
    response.dispatchEvent(new Event('toggle'));
    await settle();
    const pres = [...d.querySelectorAll('details pre')].map((p) => p.textContent);
    expect(pres[0]).toBe('{\n  "text": "q6"\n}');
    expect(pres[1]).toBe('"a6"');
  });

  it('draws the path with arrows, candidate diamonds and cameras faded after the current event', async () => {
    await open({ runId: 'f1', event: '2' });
    const cams = () => qa('.leaflet-container .geo-marker.camera');
    expect(cams().map((c) => c.textContent)).toEqual(['1', '2', '3']);
    expect(cams().map((c) => c.className.replace('geo-marker camera ', ''))).toEqual([
      'past',
      'past',
      'future',
    ]);
    expect(qa('.leaflet-container .geo-marker.pin-gtfs')[0].textContent).toBe('G');
    expect(qa('.leaflet-container .geo-marker.diamond').map((d) => d.className)).toEqual([
      expect.stringContaining('cand-confirmed'),
      expect.stringContaining('cand-rejected'),
    ]);
    expect(qa('.leaflet-container .geo-marker.arrow').length).toBeGreaterThan(0);
    expect(
      q('.leaflet-container path.leaflet-interactive, .leaflet-container path'),
    ).not.toBeNull();

    cams()[2].click();
    expect(navigate).toHaveBeenLastCalledWith(
      ['/explore', 'f1'],
      expect.objectContaining({ queryParams: { event: 3 } }),
    );
  });

  it('highlights the cameras of the current event', async () => {
    await open({ runId: 'f1', event: '1' });
    const classes = qa('.leaflet-container .geo-marker.camera').map((c) => c.className);
    expect(classes[0]).toContain('current');
    expect(classes[1]).toContain('current');
    expect(classes[2]).toContain('future');
  });

  it('draws the OSM features with the shared pins and persists the toggle', async () => {
    localStorage.removeItem('explore.osmFeatures');
    const osm = (id: string, kind: string) => ({
      id,
      kind,
      lat: 41.9005,
      lon: 12.5005,
      ref: '',
      name: '',
      operator: '',
    });
    await open({
      runId: 'f1',
      run: exploration('f1', { osm_features: [osm('n1', 'bus_stop'), osm('n2', 'shelter')] }),
    });
    const pins = () => qa('.leaflet-container .geo-marker.pin-feature');
    expect(pins().map((p) => p.textContent)).toEqual(['B', 'H']);
    expect(qa('.leaflet-container .geo-marker.pin-osm')).toHaveLength(0);
    expect(qa('.legend .pin-feature').map((p) => p.textContent)).toEqual([
      'B',
      'L',
      'S',
      'H',
      'T',
      '?',
    ]);
    expect(q('.legend')!.textContent).not.toContain('OpenStreetMap');
    expect(q('.legend')!.textContent).toContain('Submitted position');
    expect(q('.legend')!.textContent).toContain('Candidate confirmed');

    const box = q('.toggles input') as HTMLInputElement;
    expect(box.checked).toBe(true);
    box.click();
    fixture.detectChanges();
    await settle();
    expect(pins()).toHaveLength(0);
    expect(JSON.parse(localStorage.getItem('explore.osmFeatures')!)).toBe(false);
    localStorage.removeItem('explore.osmFeatures');
  });

  it('shows the filmstrip in order, marks opening photos and jumps to the photo event on click', async () => {
    await open({ runId: 'f1', event: '2' });
    const frames = qa('.film .frame');
    expect(frames.map((f) => f.textContent!.replace(/\s+/g, ' ').trim())).toEqual([
      'Photo 1forwardopening',
      'Photo 2forwardopening',
      'Photo 3across',
    ]);
    expect(frames[0].getAttribute('aria-current')).toBeNull(); // event 2 took no photo
    expect(frames[2].classList.contains('later')).toBe(true);
    frames[2].click();
    expect(navigate).toHaveBeenLastCalledWith(
      ['/explore', 'f1'],
      expect.objectContaining({ queryParams: { event: 3 } }),
    );
    frames[1].click();
    expect(navigate).toHaveBeenLastCalledWith(
      ['/explore', 'f1'],
      expect.objectContaining({ queryParams: { event: 1 } }),
    );
  });

  it('shows the API error when the run fails to load', async () => {
    fixture = TestBed.createComponent(ExplorePage);
    el = fixture.nativeElement;
    fixture.componentRef.setInput('runId', 'f9');
    fixture.detectChanges();
    TestBed.tick();
    await new Promise((r) => setTimeout(r));
    http.expectOne('/api/explorations').flush(runs);
    http
      .expectOne('/api/explorations/f9')
      .flush({ detail: 'record has an unknown layout' }, { status: 422, statusText: 'x' });
    await settle();
    expect(q('[role=alert]')!.textContent).toContain('record has an unknown layout');
    expect(q('app-run-list')).not.toBeNull(); // the list stays usable
  });

  it('shows an empty state without runs', async () => {
    await open({ runs: [] });
    expect(el.textContent).toContain('No exploration runs yet');
    expect(navigate).not.toHaveBeenCalled();
  });
});
