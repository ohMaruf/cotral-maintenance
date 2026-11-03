# review-ui

Angular frontend for the local stop review tool (scores table, Versus pairwise rating,
photo viewer). It talks to the FastAPI backend-for-frontend in `../cotral_review/`; the
contract is `../docs/review-api.md`.

Node is pinned in `.node-version` (24, via fnm: `eval "$(fnm env)" && fnm use`).

## Develop

```sh
# terminal 1: backend (repo root)
.venv/bin/python -m cotral_review serve --port 8765 [--database path/to.sqlite3]

# terminal 2
cd review-ui
npm ci
npm start            # http://localhost:4200, /api is proxied to 127.0.0.1:8765
```

## Build

```sh
npm run build        # outputs to dist/ (index.html at dist/index.html)
```

The backend serves `dist/` with SPA fallback, so after a build restart it and open
http://127.0.0.1:8765/.

## Check

```sh
npm run lint
npm run typecheck
npm run test:ci      # Vitest, single run (npm test watches)
npm run format       # Prettier (format:check to verify)
npm run check        # lint + typecheck + tests + build
```
