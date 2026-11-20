import { Routes, UrlMatcher } from '@angular/router';

export function optionalParam(prefix: string, param: string): UrlMatcher {
  return (segments) => {
    if (segments.length === 0 || segments.length > 2 || segments[0].path !== prefix) return null;
    return {
      consumed: segments,
      posParams: segments[1] ? { [param]: segments[1] } : {},
    };
  };
}

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'results' },
  {
    path: 'results',
    title: 'Results · Stop review',
    loadComponent: () => import('./features/results/results-page').then((m) => m.ResultsPage),
  },
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
  {
    matcher: optionalParam('explore', 'runId'),
    title: 'Explore · Stop review',
    loadComponent: () => import('./features/explore/explore-page').then((m) => m.ExplorePage),
  },
  {
    matcher: optionalParam('shapes', 'stopId'),
    title: 'Shapes · Stop review',
    loadComponent: () => import('./features/shapes/shapes-page').then((m) => m.ShapesPage),
  },
  { path: '**', redirectTo: 'results' },
];
