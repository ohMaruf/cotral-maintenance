import { LatLon } from '../../core/api/api.types';

// Declarative description of what a GeoMap draws. Plain data, no Leaflet types:
// feature code builds these with pure functions, GeoMap turns them into Leaflet layers.
// Later entries are drawn above earlier ones.

interface BaseLayer {
  /** Unique within one map; reported by GeoMap's `layerClick` output. */
  id: string;
  /** Plain-text tooltip. */
  tooltip?: string;
  /** Emits `layerClick` when set. */
  interactive?: boolean;
}

export interface MarkerLayer extends BaseLayer {
  type: 'marker';
  lat: number;
  lon: number;
  /** Text shown inside the marker ("G", "3", "➤"). */
  text: string;
  /** CSS classes for the marker element (styled in geo-map.scss, or by the feature). */
  className: string;
  /** Clockwise rotation of the text, in degrees. */
  rotateDeg?: number;
  /** Text colour (route-coloured arrows); markers with a background use CSS classes. */
  color?: string;
  size?: number;
  zIndexOffset?: number;
}

export interface PolylineLayer extends BaseLayer {
  type: 'polyline';
  points: LatLon[];
  color: string;
  weight?: number;
  opacity?: number;
  dashArray?: string;
}

export interface PolygonLayer extends BaseLayer {
  type: 'polygon';
  points: LatLon[];
  color: string;
  weight?: number;
  opacity?: number;
  fillOpacity?: number;
}

export type MapLayer = MarkerLayer | PolylineLayer | PolygonLayer;

export interface PositionLike {
  lat: number;
  lon: number;
}

export function toLatLon(p: PositionLike): LatLon {
  return [p.lat, p.lon];
}
