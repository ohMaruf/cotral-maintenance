import { Exploration, ExplorationPhoto } from '../../core/api/api.types';
import {
  MapLayer,
  MarkerLayer,
  PolygonLayer,
  PolylineLayer,
} from '../../shared/geo-map/map-layers';
import { distanceM } from '../../shared/lib/geo';
import {
  buildExploreLayers,
  exploreBounds,
  photoIndexOfLayer,
  photoLayerId,
} from './explore-layers';
import { exploration, photo } from './explore-testing';

const run: Exploration = exploration();

const byType = <T extends MapLayer>(layers: MapLayer[], type: T['type']) =>
  layers.filter((l): l is T => l.type === type);

describe('buildExploreLayers', () => {
  it('draws a lettered pin per position with the error in the tooltip', () => {
    const pins = byType<MarkerLayer>(
      buildExploreLayers(run, { photosUsed: 3, currentPhotos: [3] }),
      'marker',
    ).filter((m) => m.id.startsWith('pos-'));
    expect(pins.map((p) => p.text)).toEqual(['G', 'V', 'E']);
    expect(pins.map((p) => p.className)).toEqual(['pin-gtfs', 'pin-verified', 'pin-estimate']);
    expect(pins[0].tooltip).toBe('GTFS · 40.0 m from verified');
    expect(pins[1].tooltip).toBe('Verified');
  });

  it('draws OSM features below the position pins, and none when hidden', () => {
    const withOsm = exploration('f1', {
      osm_features: [
        { id: 'n9', kind: 'shelter', lat: 41.9, lon: 12.5, ref: '', name: 'Riparo', operator: '' },
      ],
    });
    const layers = buildExploreLayers(withOsm, { photosUsed: 3, currentPhotos: [3] });
    const markers = byType<MarkerLayer>(layers, 'marker');
    const feature = markers.find((m) => m.id === 'feature-n9')!;
    expect(feature.text).toBe('H');
    expect(feature.className).toBe('pin-feature');
    expect(feature.tooltip).toBe('shelter · Riparo · n9');
    expect(feature.zIndexOffset).toBeLessThan(0);
    expect(layers.indexOf(feature)).toBeLessThan(layers.findIndex((l) => l.id === 'pos-gtfs'));
    const hidden = buildExploreLayers(withOsm, {
      photosUsed: 3,
      currentPhotos: [3],
      showOsmFeatures: false,
    });
    expect(hidden.some((l) => l.id.startsWith('feature-'))).toBe(false);
  });

  it('draws a numbered, clickable camera per photo, faded after the current event', () => {
    const layers = buildExploreLayers(run, { photosUsed: 2, currentPhotos: [2] });
    const cams = byType<MarkerLayer>(layers, 'marker').filter((m) => m.id.startsWith('photo-'));
    expect(cams.map((c) => c.text)).toEqual(['1', '2', '3']);
    expect(cams.map((c) => c.className)).toEqual([
      'camera past',
      'camera current',
      'camera future',
    ]);
    expect(cams.every((c) => c.interactive)).toBe(true);
    expect(cams[1].zIndexOffset).toBeGreaterThan(0);
  });

  it('draws one cone per photo, 25 m deep, the current one emphasised and last', () => {
    const layers = buildExploreLayers(run, { photosUsed: 2, currentPhotos: [2] });
    const cones = byType<PolygonLayer>(layers, 'polygon');
    expect(cones).toHaveLength(3);
    expect(cones[cones.length - 1].id).toBe('cone-2');
    const p2 = run.photo_list[1];
    const arc = cones[2].points.slice(1);
    for (const pt of arc) expect(distanceM([p2.lat, p2.lon], pt)).toBeCloseTo(25, 1);
    const future = cones.find((c) => c.id === 'cone-3')!;
    expect(future.fillOpacity!).toBeLessThan(cones.find((c) => c.id === 'cone-1')!.fillOpacity!);
    expect(cones[2].fillOpacity!).toBeGreaterThan(cones[0].fillOpacity!);
  });

  it('draws the bus path as a polyline under everything, with arrows along it', () => {
    const layers = buildExploreLayers(run, { photosUsed: 2, currentPhotos: [2] });
    const lines = byType<PolylineLayer>(layers, 'polyline');
    expect(lines.map((l) => l.id)).toEqual(['path']);
    expect(lines[0].points).toEqual(run.path);
    expect(layers[0]).toBe(lines[0]);
    const arrows = byType<MarkerLayer>(layers, 'marker').filter((m) =>
      m.id.startsWith('path-arrow-'),
    );
    expect(arrows.length).toBeGreaterThan(0);
    expect(arrows.every((a) => a.text === '➤' && a.className === 'arrow')).toBe(true);
    // the path runs north-east: bearing ~45, drawn at bearing - 90
    expect(arrows[0].rotateDeg).toBeGreaterThan(-60);
    expect(arrows[0].rotateDeg).toBeLessThan(-20);
  });

  it('draws diamonds for candidates, coloured by status, with the evidence in the tooltip', () => {
    const diamonds = byType<MarkerLayer>(
      buildExploreLayers(run, { photosUsed: 3, currentPhotos: [3] }),
      'marker',
    ).filter((m) => m.id.startsWith('candidate-'));
    expect(diamonds.map((d) => d.className)).toEqual([
      'diamond cand-confirmed',
      'diamond cand-rejected',
    ]);
    expect(diamonds.map((d) => d.text)).toEqual(['1', '2']);
    expect(diamonds[0].tooltip).toBe(
      'Candidate 1 · sign · confirmed · evidence: cotral sign · basis: triangulated',
    );
    expect(diamonds[1].tooltip).not.toContain('evidence');
  });

  it('highlights every photo of the current event', () => {
    const layers = buildExploreLayers(run, { photosUsed: 3, currentPhotos: [1, 2] });
    const cams = byType<MarkerLayer>(layers, 'marker').filter((m) => m.id.startsWith('photo-'));
    expect(cams.map((c) => c.className)).toEqual([
      'camera current',
      'camera current',
      'camera past',
    ]);
    const cones = byType<PolygonLayer>(layers, 'polygon');
    expect(cones.slice(-2).map((c) => c.id)).toEqual(['cone-1', 'cone-2']);
  });

  it('marks the opening photos in their tooltips', () => {
    const cams = byType<MarkerLayer>(
      buildExploreLayers(run, { photosUsed: 3, currentPhotos: [] }),
      'marker',
    ).filter((m) => m.id.startsWith('photo-'));
    expect(cams[0].tooltip).toContain('(opening)');
    expect(cams[2].tooltip).toBe('Photo 3 · across · heading 120°');
  });

  it('copes with no path, candidates or photos', () => {
    const bare: Exploration = { ...run, path: [], candidates: [], photo_list: [], event_list: [] };
    const layers = buildExploreLayers(bare, { photosUsed: 0, currentPhotos: [] });
    expect(layers.filter((l) => l.type !== 'marker')).toEqual([]);
    expect(layers.map((l) => l.id)).toEqual(['pos-gtfs', 'pos-verified', 'pos-estimate']);
  });
});

describe('exploreBounds', () => {
  it('covers positions, photo and candidate locations, not the whole path', () => {
    const extra: ExplorationPhoto = photo(4, { lat: 42, lon: 13 });
    const bounds = exploreBounds({ ...run, photo_list: [...run.photo_list, extra] });
    expect(bounds).toHaveLength(run.positions.length + 4 + run.candidates.length);
    expect(bounds).toContainEqual([42, 13]);
  });
});

describe('photo layer ids', () => {
  it('round-trips', () => {
    expect(photoIndexOfLayer(photoLayerId(12))).toBe(12);
    expect(photoIndexOfLayer('pos-gtfs')).toBeNull();
  });
});
