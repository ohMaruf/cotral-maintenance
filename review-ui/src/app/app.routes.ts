import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'scores' },
  {
    path: 'scores',
    title: 'Scores · Stop review',
    loadComponent: () => import('./features/scores/scores-page').then((m) => m.ScoresPage),
  },
  {
    path: 'versus',
    title: 'Versus · Stop review',
    loadComponent: () => import('./features/versus/versus-page').then((m) => m.VersusPage),
  },
  { path: '**', redirectTo: 'scores' },
];
