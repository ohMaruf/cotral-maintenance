import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { CATALOG, stop } from '../../testing';
import { ScoresPage } from './scores-page';

const stops = [
  stop('a', { name: 'Alpha', scores: { clef: { shelter: 0.5 }, gemma: { shelter: 3 } } }),
  stop('b', { name: 'Beta', scores: { clef: { shelter: 4 }, gemma: { shelter: 4 } } }),
  stop('c', { name: 'Gamma' }),
];

describe('ScoresPage', () => {
  let fixture: ComponentFixture<ScoresPage>;
  let el: HTMLElement;

  beforeEach(async () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    fixture = TestBed.createComponent(ScoresPage);
    el = fixture.nativeElement;
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    TestBed.tick();
    await new Promise((r) => setTimeout(r));
    http.expectOne('/api/catalog').flush(CATALOG);
    http.expectOne('/api/stops').flush(stops);
    await fixture.whenStable();
  });

  const names = () => [...el.querySelectorAll('tbody th .name')].map((n) => n.textContent?.trim());

  it('renders one row per stop with a cell per category and model', () => {
    expect(names()).toEqual(['Alpha', 'Beta', 'Gamma']);
    const cells = el.querySelectorAll('tbody tr:first-child td.score');
    expect(cells).toHaveLength(CATALOG.categories.length * CATALOG.models.length);
  });

  it('highlights a category where the models disagree by 2+ levels', () => {
    const disagree = el.querySelectorAll('tbody tr:first-child td.disagree');
    expect(disagree).toHaveLength(2); // Alpha shelter: 0.5 vs 3
    expect(el.querySelectorAll('tbody tr:nth-child(2) td.disagree')).toHaveLength(0);
  });

  it('sorts from the URL param with missing values last, and filters by name', async () => {
    fixture.componentRef.setInput('sort', 'shelter:clef');
    fixture.componentRef.setInput('dir', 'asc');
    await fixture.whenStable();
    expect(names()).toEqual(['Alpha', 'Beta', 'Gamma']);

    fixture.componentRef.setInput('dir', 'desc');
    await fixture.whenStable();
    expect(names()).toEqual(['Beta', 'Alpha', 'Gamma']);

    fixture.componentRef.setInput('q', 'gam');
    await fixture.whenStable();
    expect(names()).toEqual(['Gamma']);
  });
});
