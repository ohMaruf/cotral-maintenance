import { Injectable, signal } from '@angular/core';

const STORAGE_KEY = 'review-ui.rater';

@Injectable({ providedIn: 'root' })
export class RaterService {
  private readonly _name = signal(this.read());
  readonly name = this._name.asReadonly();

  set(name: string): void {
    this._name.set(name);
    try {
      if (name.trim()) localStorage.setItem(STORAGE_KEY, name);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      return;
    }
  }

  payload(): string | null {
    return this._name().trim() || null;
  }

  private read(): string {
    try {
      return localStorage.getItem(STORAGE_KEY) ?? '';
    } catch {
      return '';
    }
  }
}
