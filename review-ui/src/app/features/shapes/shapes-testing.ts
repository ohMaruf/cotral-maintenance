import {
  OsmFeature,
  ShapeCheck,
  ShapeRoute,
  ShapeStop,
  ShapeVerdict,
} from '../../core/api/api.types';

export function route(shape: string, overrides: Partial<ShapeRoute> = {}): ShapeRoute {
  return {
    shape,
    trips: 12,
    points: [
      [41.9, 12.5],
      [41.901, 12.501],
    ],
    arrows: [{ lat: 41.9005, lon: 12.5005, bearing: 45 }],
    truth_m: 4.2,
    truth_side: 'right',
    gtfs_m: 60.1,
    prev: [],
    next: [],
    matched: [
      [
        [41.9, 12.5],
        [41.9005, 12.5006],
      ],
      [
        [41.9008, 12.5008],
        [41.901, 12.501],
      ],
    ],
    truth_path_m: 3.1,
    truth_path_side: 'right',
    ...overrides,
  };
}

export function shapeStop(id: string, overrides: Partial<ShapeStop> = {}): ShapeStop {
  return {
    id,
    name: `Stop ${id} # ${id}`,
    offset_m: 83.4,
    flags: ['moved'],
    has_sign: 'yes',
    comments: '',
    gtfs: [41.9, 12.5],
    truth: [41.9006, 12.5004],
    places: [41.9002, 12.5001],
    osm_features: [],
    routes: [route('s1'), route('s2', { trips: 3, truth_side: 'left' })],
    neighbours: [{ id: 'n1', name: 'Neighbour', lat: 41.9, lon: 12.51 }],
    ...overrides,
  };
}

export function shapeCheck(ids = ['a', 'b', 'c']): ShapeCheck {
  return {
    generated_at: '2026-11-07T08:16:18+00:00',
    min_offset_m: 50,
    stops: ids.map((id) => shapeStop(id)),
  };
}

export function verdict(stopId: string, overrides: Partial<ShapeVerdict> = {}): ShapeVerdict {
  return {
    stop_id: stopId,
    verdict: 'on_route',
    note: '',
    rater: null,
    updated_at: '2026-11-07T09:00:00Z',
    ...overrides,
  };
}

export function osmFeature(id: string, overrides: Partial<OsmFeature> = {}): OsmFeature {
  return {
    id,
    kind: 'bus_stop',
    lat: 41.9006,
    lon: 12.5004,
    ref: '',
    name: '',
    operator: '',
    ...overrides,
  };
}
