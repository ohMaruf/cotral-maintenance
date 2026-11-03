import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Dialog } from '@angular/cdk/dialog';
import { RaterService } from '../../core/services/rater.service';
import { CATALOG, judgmentResponse, nextPair, progress } from '../../testing';
import { PhotoViewerService } from '../photo-viewer/photo-viewer.service';
import { VersusPage } from './versus-page';

function press(key: string): void {
  document.body.dispatchEvent(
    new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }),
  );
}

describe('VersusPage flow', () => {
  let fixture: ComponentFixture<VersusPage>;
  let http: HttpTestingController;
  let el: HTMLElement;

  async function settle(): Promise<void> {
    await fixture.whenStable();
    fixture.detectChanges();
  }

  async function open(first = nextPair()): Promise<void> {
    fixture = TestBed.createComponent(VersusPage);
    el = fixture.nativeElement;
    http.expectOne('/api/catalog').flush(CATALOG);
    http.expectOne('/api/pairs/next').flush(first);
    await settle();
  }

  const q = (sel: string) => el.querySelector<HTMLElement>(sel);

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    TestBed.inject(Dialog).closeAll();
    http.verify();
  });

  it('shows two stops without scores and the progress', async () => {
    await open();
    expect(el.textContent).toContain('Stop a');
    expect(el.textContent).toContain('Stop b');
    expect(el.querySelectorAll('app-photo-grid')).toHaveLength(2);
    expect(q('.reveal')).toBeNull();
    expect(q('.progress')?.textContent).toContain('3');
  });

  it('pick, POST body, reveal, then next pair', async () => {
    TestBed.inject(RaterService).set('Ana');
    await open();

    q('.card .choose')!.click();
    const post = http.expectOne('/api/judgments');
    expect(post.request.method).toBe('POST');
    expect(post.request.body).toMatchObject({ left: 'a', right: 'b', winner: 'a', rater: 'Ana' });
    expect(typeof post.request.body.decision_ms).toBe('number');
    expect(post.request.body.decision_ms).toBeGreaterThanOrEqual(0);
    post.flush(judgmentResponse('a', 'b', 'a'), { status: 201, statusText: 'Created' });
    await settle();

    expect(q('.reveal')).not.toBeNull();
    expect(el.querySelectorAll('.reveal tbody tr')).toHaveLength(CATALOG.categories.length);
    expect(q('.card.picked')?.textContent).toContain('Stop a');
    const chips = [...el.querySelectorAll('.chip')].map((c) => c.textContent?.trim());
    expect(chips[0]).toContain('Clef agrees');
    expect(chips[1]).toContain('Gemma agrees');
    expect(q('.progress')?.textContent).toContain('2');
    // Choice buttons are locked after the choice.
    expect(q('.card .choose')?.hasAttribute('disabled')).toBe(true);

    press('Enter');
    http
      .expectOne('/api/pairs/next')
      .flush(nextPair('c', 'd', progress({ judged: 1, remaining: 2 })));
    await settle();
    expect(q('.reveal')).toBeNull();
    expect(el.textContent).toContain('Stop c');
  });

  it('keyboard: arrow right picks the right stop, S skips with a null winner', async () => {
    await open();
    press('ArrowRight');
    let post = http.expectOne('/api/judgments');
    expect(post.request.body.winner).toBe('b');
    post.flush(judgmentResponse('a', 'b', 'b'), { status: 201, statusText: 'Created' });
    await settle();
    // Disagreement: models say the left stop needs more maintenance.
    expect(q('.chip')?.textContent).toContain('Clef disagrees');

    press('Enter');
    http.expectOne('/api/pairs/next').flush(nextPair('c', 'd'));
    await settle();

    press('s');
    post = http.expectOne('/api/judgments');
    expect(post.request.body).toMatchObject({ left: 'c', right: 'd', winner: null });
    post.flush(judgmentResponse('c', 'd', null), { status: 201, statusText: 'Created' });
    await settle();
    expect(q('.chip')?.textContent).toContain('no pick');
  });

  it('ignores a second choice while the first is being saved', async () => {
    await open();
    press('ArrowLeft');
    press('ArrowRight');
    http
      .expectOne('/api/judgments')
      .flush(judgmentResponse(), { status: 201, statusText: 'Created' });
  });

  it('on 409 fetches the next pair without revealing', async () => {
    await open();
    press('ArrowLeft');
    http
      .expectOne('/api/judgments')
      .flush({ detail: 'pair already judged' }, { status: 409, statusText: 'Conflict' });
    http.expectOne('/api/pairs/next').flush(nextPair('c', 'd'));
    await settle();
    expect(q('.reveal')).toBeNull();
    expect(q('.notice')?.textContent).toContain('just judged');
    expect(el.textContent).toContain('Stop c');
  });

  it('keeps the pair and shows an error when saving fails', async () => {
    await open();
    press('ArrowLeft');
    http
      .expectOne('/api/judgments')
      .flush({ detail: 'db locked' }, { status: 500, statusText: 'x' });
    await settle();
    expect(q('.notice')?.textContent).toContain('db locked');
    expect(el.textContent).toContain('Stop a');
    press('ArrowLeft');
    http
      .expectOne('/api/judgments')
      .flush(judgmentResponse(), { status: 201, statusText: 'Created' });
  });

  it('shows the done state when every pair is judged', async () => {
    await open({ pair: null, progress: progress({ judged: 10, remaining: 0 }) });
    expect(el.textContent).toContain('All pairs judged');
    expect(q('.pair')).toBeNull();
  });

  it('shows an error with retry when loading fails', async () => {
    fixture = TestBed.createComponent(VersusPage);
    el = fixture.nativeElement;
    http.expectOne('/api/catalog').flush(CATALOG);
    http.expectOne('/api/pairs/next').flush({ detail: 'nope' }, { status: 500, statusText: 'x' });
    await settle();
    expect(q('[role="alert"]')?.textContent).toContain('nope');
    q('[role="alert"] button')!.click();
    http.expectOne('/api/catalog').flush(CATALOG);
    http.expectOne('/api/pairs/next').flush(nextPair());
    await settle();
    expect(el.textContent).toContain('Stop a');
  });

  it('does not fire Versus shortcuts while the photo viewer is open', async () => {
    await open();
    const viewer = TestBed.inject(PhotoViewerService);
    await viewer.open(nextPair().pair!.left.photos, 0, 'Stop a');
    await settle();
    expect(document.querySelector('app-photo-viewer')).not.toBeNull();

    press('ArrowLeft');
    press('ArrowRight');
    press('s');
    http.expectNone('/api/judgments');
    // The viewer itself handled the arrow key: it moved to photo 2.
    await new Promise((r) => setTimeout(r));
    expect(document.querySelector('.count')?.textContent).toContain('Photo 2 of 4');

    TestBed.inject(Dialog).closeAll();
    press('ArrowLeft');
    http
      .expectOne('/api/judgments')
      .flush(judgmentResponse(), { status: 201, statusText: 'Created' });
  });
});
