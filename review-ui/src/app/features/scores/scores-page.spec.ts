import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { CATALOG, stop } from '../../testing';
import { ScoresPage } from './scores-page';

const stops = [
  stop('a', { name: 'Alpha', scores: { clef: { shelter: 0.1 }, gemma: { shelter: 0.8 } } }),
  stop('b', { name: 'Beta', scores: { clef: { shelter: 1 }, gemma: { shelter: 1 } } }),
  stop('c', { name: 'Gamma' }),
];

const merged = {
  ...CATALOG,
  categories: [
    { key: 'has_shelter', label: 'Shelter present', kind: 'probability' as const, description: '' },
    { key: 'shelter', label: 'Shelter', kind: 'condition' as const, description: '' },
    { key: 'has_lamp', label: 'Street lamp', kind: 'probability' as const, description: '' },
  ],
  models: [CATALOG.models[0]],
};

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

  it('highlights a category where the models disagree by 0.5 or more', () => {
    const disagree = el.querySelectorAll('tbody tr:first-child td.disagree');
    expect(disagree).toHaveLength(2);
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

describe('ScoresPage merged elements', () => {
  it('folds presence into one column per element and says missing', async () => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    const fixture = TestBed.createComponent(ScoresPage);
    const el: HTMLElement = fixture.nativeElement;
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    TestBed.tick();
    await new Promise((r) => setTimeout(r));
    http.expectOne('/api/catalog').flush(merged);
    http.expectOne('/api/stops').flush([
      stop('a', {
        name: 'Alpha',
        scores: { clef: { has_shelter: 0.1, shelter: 0.9, has_lamp: 0.8 } },
      }),
      stop('b', {
        name: 'Beta',
        scores: { clef: { has_shelter: 0.9, shelter: 0.4, has_lamp: 0.2 } },
      }),
    ]);
    await fixture.whenStable();

    const heads = [...el.querySelectorAll('thead th')].map((t) => t.textContent?.trim());
    expect(heads).toEqual(['Stop', 'Photos', 'Shelter', 'Lamp']);
    const [alpha, beta] = [...el.querySelectorAll('tbody tr')];
    expect(alpha.querySelectorAll('td.score')).toHaveLength(2);
    expect(alpha.querySelector('td.score .missing')!.textContent).toContain('0.10');
    expect(alpha.querySelector('td.score .present')!.textContent).toContain('present');
    expect(beta.querySelector('td.score app-score-bar')).not.toBeNull();
    expect(beta.querySelector('td.score:nth-child(4) .missing')).not.toBeNull();

    fixture.componentRef.setInput('sort', 'has_shelter:clef');
    await fixture.whenStable();
    expect([...el.querySelectorAll('tbody th .name')].map((n) => n.textContent?.trim())).toEqual([
      'Alpha',
      'Beta',
    ]);
  });
});
