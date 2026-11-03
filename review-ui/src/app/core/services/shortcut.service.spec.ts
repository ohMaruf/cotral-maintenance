import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, Injector, runInInjectionContext } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import type { Mock } from 'vitest';
import { ShortcutHandler, ShortcutService } from './shortcut.service';

@Component({ template: '<p>dialog</p>', changeDetection: ChangeDetectionStrategy.OnPush })
class Dummy {}

function press(
  key: string,
  init: KeyboardEventInit = {},
  target: EventTarget = document,
): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
}

describe('ShortcutService', () => {
  let left: Mock<ShortcutHandler>;
  let enter: Mock<ShortcutHandler>;

  beforeEach(() => {
    left = vi.fn<ShortcutHandler>();
    enter = vi.fn<ShortcutHandler>();
    const injector = TestBed.inject(Injector);
    runInInjectionContext(injector, () =>
      TestBed.inject(ShortcutService).listen({ arrowleft: left, enter }),
    );
  });

  it('fires the matching handler', () => {
    press('ArrowLeft');
    expect(left).toHaveBeenCalledTimes(1);
  });

  it('ignores typing in fields, modifiers and key repeat', () => {
    const input = document.createElement('input');
    document.body.append(input);
    press('ArrowLeft', {}, input);
    press('ArrowLeft', { metaKey: true });
    press('ArrowLeft', { repeat: true });
    input.remove();
    expect(left).not.toHaveBeenCalled();
  });

  it('leaves Enter on a focused button to its native click', () => {
    const button = document.createElement('button');
    document.body.append(button);
    press('Enter', {}, button);
    button.remove();
    expect(enter).not.toHaveBeenCalled();
  });

  it('does not fire while a dialog (the photo viewer) is open, and resumes after', () => {
    const ref = TestBed.inject(Dialog).open(Dummy);
    press('ArrowLeft');
    expect(left).not.toHaveBeenCalled();
    ref.close();
    press('ArrowLeft');
    expect(left).toHaveBeenCalledTimes(1);
  });
});
