import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ResultRow } from '../../core/api/api.types';
import { PhotoViewerService } from '../photo-viewer/photo-viewer.service';
import { RUN_INFO, resultRow } from './results-testing';
import { ResultsPage } from './results-page';

const rows: ResultRow[] = [
  resultRow('a', { rank: 1, name: 'Alpha', priority: 0.8, shelter: 4 }),
  resultRow('b', { rank: 2, name: 'Beta', priority: 0.3, shelter: 0 }),
  resultRow('c', {
    rank: null,
    name: 'Gamma',
    needs_review: true,
    review_reason: 'the explorer did not find the stop (call cap)',
    status: 'not_found',
    shelter: null,
    seating: null,
    lighting: null,
    waiting_area: null,
    accessibility: null,
    priority: null,
    stop_visible: null,
    found_from_gtfs_m: null,
    evidence: null,
    photos: [],
  }),
];

describe('ResultsPage', () => {
  let fixture: ComponentFixture<ResultsPage>;
  let el: HTMLElement;

  beforeEach(async () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    fixture = TestBed.createComponent(ResultsPage);
    el = fixture.nativeElement;
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    TestBed.tick();
    await new Promise((r) => setTimeout(r));
    http.expectOne('/api/run').flush(RUN_INFO);
    http.expectOne('/api/results').flush(rows);
    await fixture.whenStable();
  });

  const names = () => [...el.querySelectorAll('tbody th .name')].map((n) => n.textContent?.trim());
  const text = (selector: string) => el.querySelector(selector)!.textContent!.replace(/\s+/g, ' ');

  it('shows the run: size, outcomes, scored, review count, billing and profile', () => {
    const head = text('header.run');
    expect(head).toContain('smoke-local');
    expect(head).toContain('Stops4');
    expect(head).toContain('2 found');
    expect(head).toContain('1 not found');
    expect(head).toContain('1 no imagery');
    expect(head).toContain('Scored2');
    expect(head).toContain('Needs review1');
    expect(head).toContain('6 Static, 40 tiles');
    expect(head).toContain('local-smoke-gguf');
  });

  it('lists the stops in the run order with rank, scores and a link to the exploration', () => {
    expect(names()).toEqual(['Alpha', 'Beta', 'Gamma']);
    const first = el.querySelector('tbody tr')!;
    expect(first.querySelector('.rank')!.textContent).toBe('1');
    expect(first.querySelectorAll('td.score')).toHaveLength(7);
    expect(first.querySelector('a.name')!.getAttribute('href')).toBe('/explore/a');
    expect(first.querySelector('.nowrap')!.textContent).toContain('42.4 m');
    expect(el.querySelectorAll('tbody tr')[2].querySelector('.rank')!.textContent).toBe('–');
  });

  it('shows the stop photos as thumbnails and opens them in the viewer', () => {
    expect(el.querySelectorAll('tbody tr:first-child .thumb img')).toHaveLength(1);
    expect(el.querySelectorAll('tbody tr:nth-child(3) .thumb')).toHaveLength(0);
    expect(el.querySelector('tbody tr:nth-child(3) .none')!.textContent).toContain('No photos');
    const open = vi.spyOn(TestBed.inject(PhotoViewerService), 'open').mockResolvedValue();
    el.querySelector<HTMLElement>('tbody tr:first-child .thumb')!.click();
    expect(open).toHaveBeenCalledOnce();
    expect(open.mock.calls[0][0][0].url).toBe(rows[0].photos[0]);
    expect(open.mock.calls[0][0][0].copyright).toBe('© Google');
    expect(open.mock.calls[0][2]).toBe('Alpha');
  });

  it('marks the stops that need review with their reason', () => {
    const review = el.querySelectorAll('tbody tr.review');
    expect(review).toHaveLength(1);
    expect(review[0].textContent).toContain('Gamma');
    expect(review[0].textContent).toContain('the explorer did not find the stop (call cap)');
    expect(review[0].textContent).toContain('Not found');
  });

  it('filters by "needs review" and by name, from the URL', async () => {
    fixture.componentRef.setInput('show', 'review');
    await fixture.whenStable();
    expect(names()).toEqual(['Gamma']);
    fixture.componentRef.setInput('show', 'ranked');
    await fixture.whenStable();
    expect(names()).toEqual(['Alpha', 'Beta']);
    fixture.componentRef.setInput('show', undefined);
    fixture.componentRef.setInput('q', 'bet');
    await fixture.whenStable();
    expect(names()).toEqual(['Beta']);
    expect(text('.count')).toContain('Showing 1 of 3 stops');
  });

  it('sorts by a score with missing values last, and flips the direction', async () => {
    fixture.componentRef.setInput('sort', 'shelter');
    await fixture.whenStable();
    expect(names()).toEqual(['Alpha', 'Beta', 'Gamma']);
    expect(el.querySelector('th[aria-sort="descending"]')!.textContent).toContain('Shelter');
    fixture.componentRef.setInput('dir', 'asc');
    await fixture.whenStable();
    expect(names()).toEqual(['Beta', 'Alpha', 'Gamma']);
    expect(el.querySelector('th[aria-sort="ascending"]')).not.toBeNull();
  });

  it('says so when nothing matches', async () => {
    fixture.componentRef.setInput('q', 'zzz');
    await fixture.whenStable();
    expect(el.querySelector('table')).toBeNull();
    expect(el.textContent).toContain('No stops match');
  });
});

describe('ResultsPage errors', () => {
  it('shows the API error with a retry', async () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    const fixture = TestBed.createComponent(ResultsPage);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    TestBed.tick();
    await new Promise((r) => setTimeout(r));
    http.expectOne('/api/run').flush({ detail: 'no run' }, { status: 500, statusText: 'x' });
    http.match('/api/results');
    await fixture.whenStable();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Could not load the results');
    expect(fixture.nativeElement.textContent).toContain('no run');
  });
});
