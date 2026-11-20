import { DOCUMENT } from '@angular/common';
import { Injectable, inject, signal } from '@angular/core';

export type ThemeChoice = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'review-ui.theme';
const ORDER: ThemeChoice[] = ['light', 'dark', 'system'];

@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly root = inject(DOCUMENT).documentElement;
  private readonly _choice = signal<ThemeChoice>(this.read());
  readonly choice = this._choice.asReadonly();

  constructor() {
    this.apply(this._choice());
  }

  cycle(): void {
    const next = ORDER[(ORDER.indexOf(this._choice()) + 1) % ORDER.length];
    this._choice.set(next);
    this.apply(next);
    try {
      if (next === 'system') localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, next);
    } catch {
      return;
    }
  }

  private apply(choice: ThemeChoice): void {
    if (choice === 'system') delete this.root.dataset['theme'];
    else this.root.dataset['theme'] = choice;
  }

  private read(): ThemeChoice {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored === 'light' || stored === 'dark' ? stored : 'system';
    } catch {
      return 'system';
    }
  }
}
