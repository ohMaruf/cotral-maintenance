import { MapLayer, MarkerLayer, PolylineLayer } from '../../shared/geo-map/map-layers';
import {
  ROUTE_COLORS,
  buildShapeLayers,
  distancesToVerified,
  mapsSearchUrl,
  routeColor,
  shapeBounds,
  shortName,
  streetViewUrl,
  DEFAULT_TOGGLES,
  filterByFlag,
  flagLabel,
  flagsPresent,
  loadToggles,
  nearbyFeatures,
  saveToggles,
  truthPathText,
} from './shapes-layers';
import { osmFeature, route, shapeStop } from './shapes-testing';

const markers = (layers: MapLayer[]) => layers.filter((l): l is MarkerLayer => l.type === 'marker');
const lines = (layers: MapLayer[]) =>
  layers.filter((l): l is PolylineLayer => l.type === 'polyline');

describe('buildShapeLayers', () => {
  const stop = shapeStop('a');
  const layers = buildShapeLayers(stop);

  it('draws the raw shape thin and dashed in the palette colour', () => {
    const routes = lines(layers).filter((l) => l.id.startsWith('route-'));
    expect(routes.map((r) => r.color)).toEqual([ROUTE_COLORS[0], ROUTE_COLORS[1]]);
    expect(routes.map((r) => r.weight)).toEqual([2, 2]);
    expect(routes.map((r) => r.dashArray)).toEqual(['6 6', '6 6']);
    expect(routes[0].opacity).toBe(0.8);
    expect(routes[0].tooltip).toBe('shape s1 · 12 trips');
    expect(routes[1].tooltip).toBe('shape s2 · 3 trips');
  });

  it('draws each snapped piece as a solid weight-4 line in the same colour', () => {
    const snapped = lines(layers).filter((l) => l.id.startsWith('snapped-'));
    expect(snapped.map((l) => l.id)).toEqual([
      'snapped-s1-0',
      'snapped-s1-1',
      'snapped-s2-0',
      'snapped-s2-1',
    ]);
    expect(snapped.every((l) => l.weight === 4 && l.dashArray === undefined)).toBe(true);
    expect(snapped[0].color).toBe(ROUTE_COLORS[0]);
    expect(snapped[2].color).toBe(ROUTE_COLORS[1]);
    expect(snapped[0].tooltip).toBe('shape s1 · snapped to roads');
    expect(snapped[0].points).toEqual(stop.routes[0].matched![0]);
  });

  it('draws the raw shape solid when the route is not snapped', () => {
    const l = buildShapeLayers(shapeStop('x', { routes: [route('s1', { matched: null })] }));
    const raw = lines(l).filter((x) => x.id.startsWith('route-'));
    expect(raw).toHaveLength(1);
    expect(raw[0]).toMatchObject({ weight: 4, tooltip: 'shape s1 · 12 trips' });
    expect(raw[0].dashArray).toBeUndefined();
    expect(lines(l).some((x) => x.id.startsWith('snapped-'))).toBe(false);
  });

  it('draws one snapped piece per polyline and skips degenerate pieces', () => {
    const l = buildShapeLayers(
      shapeStop('x', {
        routes: [
          route('s1', {
            matched: [
              [[1, 2]],
              [
                [1, 2],
                [3, 4],
              ],
            ],
          }),
        ],
      }),
    );
    expect(
      lines(l)
        .filter((x) => x.id.startsWith('snapped-'))
        .map((x) => x.id),
    ).toEqual(['snapped-s1-1']);
  });

  it('honours the raw and snapped toggles; arrows stay while either is on', () => {
    const only = (raw: boolean, snapped: boolean, features = true) =>
      buildShapeLayers(stop, { raw, snapped, features });
    const ids = (l: MapLayer[], prefix: string) => l.filter((x) => x.id.startsWith(prefix)).length;
    const noRaw = only(false, true);
    expect(ids(noRaw, 'route-')).toBe(0);
    expect(ids(noRaw, 'snapped-')).toBe(4);
    expect(ids(noRaw, 'arrow-')).toBe(2);
    const noSnapped = only(true, false);
    expect(ids(noSnapped, 'route-')).toBe(2);
    expect(ids(noSnapped, 'snapped-')).toBe(0);
    const none = only(false, false);
    expect(ids(none, 'route-') + ids(none, 'snapped-') + ids(none, 'arrow-')).toBe(0);
    expect(ids(none, 'pin-')).toBe(3);
  });

  it('draws direction arrows rotated to bearing - 90 in the route colour', () => {
    const arrows = markers(layers).filter((m) => m.id.startsWith('arrow-'));
    expect(arrows).toHaveLength(2);
    expect(arrows[0]).toMatchObject({ text: '➤', rotateDeg: -45, color: ROUTE_COLORS[0] });
    expect(arrows[1].color).toBe(ROUTE_COLORS[1]);
  });

  it('draws neighbours as dots with "id name" tooltips', () => {
    const dot = markers(layers).find((m) => m.id === 'neighbour-n1')!;
    expect(dot.className).toBe('dot');
    expect(dot.tooltip).toBe('n1 Neighbour');
  });

  it('draws a dashed white line from G to V and the pins above everything', () => {
    const link = lines(layers).find((l) => l.id === 'gtfs-to-verified')!;
    expect(link.color).toBe('white');
    expect(link.dashArray).toBeDefined();
    expect(link.points).toEqual([stop.gtfs, stop.truth]);
    const pins = markers(layers).filter((m) => m.id.startsWith('pin-'));
    expect(pins.map((p) => p.text)).toEqual(['G', 'P', 'V']);
    expect(layers.slice(-3).map((l) => l.id)).toEqual(['pin-gtfs', 'pin-places', 'pin-verified']);
  });

  it('wraps colours past the palette', () => {
    const many = shapeStop('x', {
      places: null,
      routes: Array.from({ length: 7 }, (_, i) => route(`r${i}`)),
    });
    const l = buildShapeLayers(many);
    expect(
      markers(l)
        .filter((m) => m.id.startsWith('pin-'))
        .map((p) => p.text),
    ).toEqual(['G', 'V']);
    expect(routeColor(6)).toBe(ROUTE_COLORS[0]);
    expect(lines(l).filter((x) => x.id.startsWith('route-'))).toHaveLength(7);
  });

  it('has no routes layers for a stop without shapes', () => {
    const l = buildShapeLayers(shapeStop('x', { routes: [] }));
    expect(lines(l).map((x) => x.id)).toEqual(['gtfs-to-verified']);
  });
});

describe('OSM feature pins', () => {
  const stop = shapeStop('a', {
    osm_features: [
      osmFeature('n1', { kind: 'bus_stop', ref: 'A1', name: 'Via Roma', operator: 'Cotral' }),
      osmFeature('w2', { kind: 'platform' }),
      osmFeature('n3', { kind: 'stop_position' }),
      osmFeature('n4', { kind: 'shelter' }),
      osmFeature('n5', { kind: 'bus_station' }),
      osmFeature('n6', { kind: 'future_kind' }),
    ],
  });

  it('draws the shared OSM feature pins below the G/P/V pins', () => {
    const l = markers(buildShapeLayers(stop));
    const pins = l.filter((m) => m.id.startsWith('feature-'));
    expect(pins.map((p) => p.text)).toEqual(['B', 'L', 'S', 'H', 'T', '?']);
    const gtfs = l.find((m) => m.id === 'pin-gtfs')!;
    expect(pins[0].zIndexOffset).toBeLessThan(0);
    expect(gtfs.zIndexOffset).toBeGreaterThan(0);
    expect(l.indexOf(gtfs)).toBeGreaterThan(l.indexOf(pins[0]));
  });

  it('draws no feature pins when the toggle is off', () => {
    const l = buildShapeLayers(stop, { ...DEFAULT_TOGGLES, features: false });
    expect(l.some((x) => x.id.startsWith('feature-'))).toBe(false);
  });

  it('lists features within 200 m nearest first with ref and name', () => {
    const s = shapeStop('a', {
      truth: [41.9, 12.5],
      osm_features: [
        osmFeature('far', { lat: 41.9, lon: 12.5 + 0.0031 }),
        osmFeature('b', { lat: 41.9009, lon: 12.5, ref: 'R', name: 'N' }),
        osmFeature('a', { lat: 41.9, lon: 12.5008 }),
      ],
    });
    const out = nearbyFeatures(s);
    expect(out.map((x) => x.feature.id)).toEqual(['a', 'b']);
    expect(out.map((x) => x.m)).toEqual([66, 100]);
    expect(out[1].text).toBe('R · N');
  });
});

describe('layer toggles storage', () => {
  afterEach(() => {
    localStorage.removeItem('shapes.layers');
    vi.restoreAllMocks();
  });

  it('defaults to all on and round-trips', () => {
    expect(loadToggles()).toEqual(DEFAULT_TOGGLES);
    saveToggles({ raw: false, snapped: true, features: false });
    expect(loadToggles()).toEqual({ raw: false, snapped: true, features: false });
  });

  it('ignores corrupt data and unavailable storage', () => {
    localStorage.setItem('shapes.layers', '{nope');
    expect(loadToggles()).toEqual(DEFAULT_TOGGLES);
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(loadToggles()).toEqual(DEFAULT_TOGGLES);
    expect(() => saveToggles(DEFAULT_TOGGLES)).not.toThrow();
  });
});

describe('flags', () => {
  it('labels the known flags and passes unknown ones through', () => {
    expect(flagLabel('moved', 50)).toBe('Moved ≥ 50 m');
    expect(flagLabel('left_of_path', 50)).toBe('Left of path');
    expect(flagLabel('far_from_path', 50)).toBe('Far from path');
    expect(flagLabel('on_detour', 50)).toBe('On a detour');
    expect(flagLabel('mystery', 50)).toBe('mystery');
  });

  const stops = [
    shapeStop('a', { flags: ['on_detour', 'moved'] }),
    shapeStop('b', { flags: ['zeta'] }),
    shapeStop('c', { flags: ['moved', 'alpha'] }),
  ];

  it('lists the flags present, known first in contract order then unknown sorted', () => {
    expect(flagsPresent(stops)).toEqual(['moved', 'on_detour', 'alpha', 'zeta']);
  });

  it('filters by flag, null meaning all', () => {
    expect(filterByFlag(stops, null).map((s) => s.id)).toEqual(['a', 'b', 'c']);
    expect(filterByFlag(stops, 'moved').map((s) => s.id)).toEqual(['a', 'c']);
    expect(filterByFlag(stops, 'nothing')).toEqual([]);
  });

  it('formats V → path', () => {
    expect(truthPathText({ truth_path_m: 4.2, truth_path_side: 'left' })).toBe('4.2 m left');
    expect(truthPathText({ truth_path_m: null, truth_path_side: null })).toBe('–');
  });
});

describe('shapeBounds and distances', () => {
  it('fits G, V and P when present', () => {
    const s = shapeStop('a');
    expect(shapeBounds(s)).toEqual([s.gtfs, s.truth, s.places]);
    expect(shapeBounds(shapeStop('b', { places: null }))).toHaveLength(2);
  });

  it('measures G and P to V in whole metres', () => {
    const s = shapeStop('a', { gtfs: [41.9, 12.5], truth: [41.9009, 12.5], places: null });
    const d = distancesToVerified(s);
    expect(d.map((x) => x.key)).toEqual(['G']);
    expect(d[0].m).toBe(100);
    expect(distancesToVerified(shapeStop('b')).map((x) => x.key)).toEqual(['G', 'P']);
  });
});

describe('links and names', () => {
  it('builds the Google Maps urls', () => {
    expect(streetViewUrl([1.5, 2.5])).toBe(
      'https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=1.5,2.5',
    );
    expect(mapsSearchUrl([1.5, 2.5])).toBe(
      'https://www.google.com/maps/search/?api=1&query=1.5,2.5',
    );
  });

  it('strips the trailing id from names', () => {
    expect(shortName('CASTROCIELO | Via Leuciana # f7188')).toBe('CASTROCIELO | Via Leuciana');
    expect(shortName('Plain')).toBe('Plain');
  });
});
