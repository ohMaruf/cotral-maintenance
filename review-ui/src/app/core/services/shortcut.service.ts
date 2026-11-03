import { Dialog } from '@angular/cdk/dialog';
import { DestroyRef, Injectable, inject } from '@angular/core';
import { DOCUMENT } from '@angular/common';

export type ShortcutHandler = (event: KeyboardEvent) => void;

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}

function isActivatable(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && ['BUTTON', 'A', 'SUMMARY'].includes(target.tagName);
}

/**
 * Page-level keyboard shortcuts. Keys are matched on `KeyboardEvent.key`
 * (lower-cased). Shortcuts do not fire while any CDK dialog (the photo viewer)
 * is open, while typing in a form field, with modifier keys held, on key repeat,
 * or for Enter / Space on a focused button or link (their native click wins).
 */
@Injectable({ providedIn: 'root' })
export class ShortcutService {
  private readonly dialog = inject(Dialog);
  private readonly document = inject(DOCUMENT);

  /**
   * Registers handlers until the calling injection context is destroyed.
   * Call from a component or service constructor / field initialiser.
   */
  listen(handlers: Record<string, ShortcutHandler>): void {
    const onKeydown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.repeat) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (this.dialog.openDialogs.length > 0) return;
      if (isEditable(event.target)) return;
      const key = event.key.toLowerCase();
      if ((key === 'enter' || key === ' ') && isActivatable(event.target)) return;
      const handler = handlers[key];
      if (!handler) return;
      event.preventDefault();
      handler(event);
    };
    this.document.addEventListener('keydown', onKeydown);
    inject(DestroyRef).onDestroy(() => this.document.removeEventListener('keydown', onKeydown));
  }
}
