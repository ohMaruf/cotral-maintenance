import { ExplorationPhoto } from '../../core/api/api.types';
import {
  formatDuration,
  formatMeters,
  formatTimestamp,
  outcomeInfo,
  towardLabel,
  budgetLabel,
  billedLabel,
  budgetDetail,
  prettyJson,
  modelsLabel,
  shortCommit,
  startLabel,
  tilesLabel,
  versionLabel,
  runDuration,
  toViewerPhoto,
} from './explore-format';
import {
  exploration,
  photo,
  imagesExploration,
  sweepExploration,
  harness,
  summary,
} from '../../features/explore/explore-testing';

describe('explore-format', () => {
  it('labels known outcomes and passes unknown ones through', () => {
    expect(outcomeInfo('found')).toEqual({ label: 'Found', tone: 'ok' });
    expect(outcomeInfo('not_found')).toEqual({ label: 'Not found', tone: 'warn' });
    expect(outcomeInfo('no_imagery').tone).toBe('bad');
    expect(outcomeInfo('failed').tone).toBe('bad');
    expect(outcomeInfo('running')).toEqual({ label: 'Running', tone: 'neutral' });
    expect(outcomeInfo('lost_in_space')).toEqual({ label: 'lost in space', tone: 'neutral' });
  });

  it('formats metres', () => {
    expect(formatMeters(null)).toBe('–');
    expect(formatMeters(4.26)).toBe('4.3 m');
    expect(formatMeters(123.4)).toBe('123 m');
  });

  it('formats durations', () => {
    expect(formatDuration(null)).toBeNull();
    expect(formatDuration(-1)).toBeNull();
    expect(formatDuration(2.34)).toBe('2.3 s');
    expect(formatDuration(42.4)).toBe('42 s');
    expect(formatDuration(125)).toBe('2 min 05 s');
    expect(formatDuration(3725)).toBe('1 h 02 min');
  });

  it('computes a run duration from ISO timestamps', () => {
    expect(runDuration('2026-01-01T10:00:00Z', '2026-01-01T10:03:10Z')).toBe('3 min 10 s');
    expect(runDuration(null, '2026-01-01T10:00:00Z')).toBeNull();
    expect(runDuration('nope', '2026-01-01T10:00:00Z')).toBeNull();
  });

  it('formats timestamps in UTC', () => {
    expect(formatTimestamp('2026-11-07T08:16:18+00:00')).toBe('2026-11-07 08:16 UTC');
    expect(formatTimestamp(null)).toBe('–');
    expect(formatTimestamp('garbage')).toBe('garbage');
  });

  it('pretty-prints JSON, even for odd values', () => {
    expect(prettyJson({ a: 1 })).toBe('{\n  "a": 1\n}');
    expect(prettyJson(undefined)).toBe('undefined');
    const cyclic: Record<string, unknown> = {};
    cyclic['self'] = cyclic;
    expect(prettyJson(cyclic)).toBe('[object Object]');
  });

  it('shows the budget with its unit', () => {
    expect(budgetLabel(3, 12, 'sweeps')).toBe('3/12 sweeps');
    expect(budgetLabel(3, 14, 'photos')).toBe('3/14 photos');
    expect(budgetLabel(5, 12, 'images')).toBe('5/12 images');
  });

  it('details the sweep budget with zooms and confirmations, but not an old run', () => {
    expect(budgetDetail(sweepExploration())).toBe('1/12 sweeps, 1 zooms, 1 confirmations');
    expect(budgetDetail(exploration())).toBe('3/14 photos');
    expect(budgetDetail(imagesExploration())).toBe('3/12 images, 1 zooms, 1 confirmations');
  });

  it('says what Google billed, only when the run records it', () => {
    expect(billedLabel(imagesExploration())).toBe('4 images (2 stop photos taken)');
    expect(billedLabel(imagesExploration('i', { stop_photos_used: 0 }))).toBe('4 images');
    expect(billedLabel(sweepExploration())).toBeNull();
  });

  it('words where a photo looks', () => {
    const photos = sweepExploration().photo_list;
    expect(towardLabel(photos[0], photos)).toBe('sweep ahead-right');
    expect(towardLabel(photos[1], photos)).toBe('sweep behind-right');
    expect(towardLabel(photos[2], photos)).toBe('zoom ×8 of photo 1');
    expect(towardLabel(photos[2])).toBe('zoom of photo 1');
    expect(towardLabel(photos[3], photos)).toBe('confirm');
    expect(towardLabel(photo(9, { toward: 'across' }), [])).toBe('across');
    expect(towardLabel(photo(9, { toward: 'stop_photo' }), [])).toBe('stop photo');
  });

  it('adapts a photo for the viewer', () => {
    const photo = {
      index: 2,
      url: '/u.jpg',
      heading: 90,
      opening: true,
      copyright: '© Google',
    } as ExplorationPhoto;
    expect(toViewerPhoto(photo)).toMatchObject({
      url: '/u.jpg',
      heading: 90,
      copyright: '© Google',
      description: 'Photo 2 (opening)',
    });
  });
});

describe('harness formatting', () => {
  it('says what was billed by request kind, tiles used, and the start', () => {
    const run = summary('h', { billed_static: 3, billed_tiles: 10, tiles_used: 12, tiles_max: 42 });
    expect(billedLabel(run)).toBe('3 Static, 10 tiles');
    expect(tilesLabel(run)).toBe('12/42 tiles');
    expect(tilesLabel(summary('o'))).toBeNull();
    expect(startLabel('osm_ref')).toBe('OSM by ref');
    expect(startLabel('osm_nearest')).toBe('OSM nearest');
    expect(startLabel('new_kind')).toBe('new kind');
    expect(startLabel(null)).toBeNull();
  });

  it('labels versions, commits and models', () => {
    expect(versionLabel('0.6.0')).toBe('v0.6.0');
    expect(versionLabel('unversioned')).toBe('unversioned');
    expect(shortCommit('da028ea9b183')).toBe('da028ea');
    expect(shortCommit(null)).toBeNull();
    expect(modelsLabel(harness())).toBe('haiku');
    expect(modelsLabel(harness('0.6.0', { confirmer_model: 'sonnet' }))).toBe(
      'explorer haiku, confirmer sonnet',
    );
    expect(
      modelsLabel(harness('0.6.0', { explorer_model: null, confirmer_model: null })),
    ).toBeNull();
  });

  it('labels look_from and aimed photos', () => {
    expect(towardLabel(photo(1, { toward: 'look_from' }))).toBe('look from another panorama');
    expect(towardLabel(photo(1, { toward: 'aimed' }))).toBe('opening, aimed at the start');
  });
});
