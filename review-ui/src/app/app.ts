import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { LucideMonitor, LucideMoon, LucideSun } from '@lucide/angular';
import { ThemeChoice, ThemeService } from './core/services/theme.service';

const LABELS = { light: 'light', dark: 'dark', system: 'system' };
const NEXT: Record<ThemeChoice, ThemeChoice> = { light: 'dark', dark: 'system', system: 'light' };

@Component({
  selector: 'app-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, LucideSun, LucideMoon, LucideMonitor],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  protected readonly theme = inject(ThemeService);
  protected readonly themeHint = computed(() => {
    const choice = this.theme.choice();
    return `Theme: ${LABELS[choice]}. Switch to ${LABELS[NEXT[choice]]}`;
  });
}
