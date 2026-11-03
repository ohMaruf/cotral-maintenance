import { Dialog } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { photo } from '../../testing';
import { PhotoViewerService } from './photo-viewer.service';

function press(key: string): void {
  document.body.dispatchEvent(
    new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }),
  );
}

const tick = () => new Promise((r) => setTimeout(r));
const q = (sel: string) => document.querySelector<HTMLElement>(sel);

describe('PhotoViewer', () => {
  const photos = [1, 2, 3].map((n) => photo('a', n));

  beforeEach(async () => {
    await TestBed.inject(PhotoViewerService).open(photos, 1, 'Stop a');
    await tick();
  });

  afterEach(() => TestBed.inject(Dialog).closeAll());

  it('opens at the given photo with a visible caption incl. copyright', () => {
    expect(q('.count')?.textContent).toContain('Photo 2 of 3');
    const caption = q('.caption')!.textContent!;
    expect(caption).toContain('Photo 2 of a');
    expect(caption).toContain('48 m');
    expect(caption).toContain('180° S');
    expect(caption).toContain('© Google');
  });

  it('moves between photos with the arrow keys and stops at the ends', async () => {
    press('ArrowRight');
    press('ArrowRight');
    await tick();
    expect(q('.count')?.textContent).toContain('Photo 3 of 3');
    press('ArrowLeft');
    press('ArrowLeft');
    press('ArrowLeft');
    await tick();
    expect(q('.count')?.textContent).toContain('Photo 1 of 3');
  });

  it('zooms with + / - and resets with 0', async () => {
    expect(q('.level')?.textContent?.trim()).toBe('100%');
    press('+');
    await tick();
    expect(q('.image')?.style.transform).toContain('scale(1.5)');
    press('-');
    await tick();
    expect(q('.image')?.style.transform).toContain('scale(1)');
    press('+');
    press('0');
    await tick();
    expect(q('.image')?.style.transform).toContain('scale(1)');
  });

  it('closes on Escape', () => {
    document.body.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }),
    );
    expect(TestBed.inject(Dialog).openDialogs).toHaveLength(0);
  });
});
