import { UrlSegment } from '@angular/router';
import { optionalParam } from './app.routes';

const segs = (...paths: string[]) => paths.map((p) => new UrlSegment(p, {}));

describe('optionalParam', () => {
  const match = optionalParam('explore', 'runId');

  it('matches the bare prefix without a param', () => {
    expect(match(segs('explore'), null!, null!)?.posParams).toEqual({});
  });

  it('matches the prefix with a param', () => {
    const r = match(segs('explore', 'f1'), null!, null!);
    expect(r?.posParams?.['runId'].path).toBe('f1');
    expect(r?.consumed).toHaveLength(2);
  });

  it('rejects other prefixes and deeper paths', () => {
    expect(match(segs('shapes'), null!, null!)).toBeNull();
    expect(match(segs('explore', 'a', 'b'), null!, null!)).toBeNull();
    expect(match([], null!, null!)).toBeNull();
  });
});
