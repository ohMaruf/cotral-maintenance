import { MarkerLayer } from './map-layers';
import {
  OSM_LEGEND,
  buildOsmFeatureLayers,
  featureCode,
  featureTooltip,
  loadShowFeatures,
  saveShowFeatures,
} from './osm-features';

const feature = (id: string, kind: string, extra: object = {}) => ({
  id,
  kind,
  lat: 41.9,
  lon: 12.5,
  ref: '',
  name: '',
  operator: '',
  ...extra,
});

describe('buildOsmFeatureLayers', () => {
  const features = [
    feature('n1', 'bus_stop', { ref: 'A1', name: 'Via Roma', operator: 'Cotral' }),
    feature('w2', 'platform'),
    feature('n3', 'stop_position'),
    feature('n4', 'shelter'),
    feature('n5', 'bus_station'),
    feature('n6', 'future_kind'),
  ];
  const pins = buildOsmFeatureLayers(features) as MarkerLayer[];

  it('draws a small lettered pin per feature', () => {
    expect(pins.map((p) => p.text)).toEqual(['B', 'L', 'S', 'H', 'T', '?']);
    expect(pins.map((p) => p.id)).toEqual(features.map((f) => `feature-${f.id}`));
    expect(pins.every((p) => p.className === 'pin-feature' && (p.size ?? 22) < 22)).toBe(true);
    expect(featureCode('bus_stop')).toBe('B');
  });

  it('puts the pins below the position pins', () => {
    expect(pins.every((p) => (p.zIndexOffset ?? 0) < 0)).toBe(true);
  });

  it('builds the tooltip from the non-empty parts', () => {
    expect(pins[0].tooltip).toBe('bus_stop · A1 · Via Roma · Cotral · n1');
    expect(featureTooltip(features[1])).toBe('platform · w2');
  });

  it('draws nothing without features', () => {
    expect(buildOsmFeatureLayers([])).toEqual([]);
  });

  it('has a legend entry per kind, plus other', () => {
    expect(OSM_LEGEND.map((l) => l.code)).toEqual(['B', 'L', 'S', 'H', 'T', '?']);
  });
});

describe('persisted toggle', () => {
  const KEY = 'test.osm-features';
  afterEach(() => localStorage.removeItem(KEY));

  it('defaults to on and round-trips', () => {
    expect(loadShowFeatures(KEY)).toBe(true);
    saveShowFeatures(KEY, false);
    expect(loadShowFeatures(KEY)).toBe(false);
  });

  it('ignores corrupt values', () => {
    localStorage.setItem(KEY, '{nope');
    expect(loadShowFeatures(KEY)).toBe(true);
  });
});
