import { LatLon } from '../../core/api/api.types';

interface BaseLayer {
  id: string;

  tooltip?: string;

  interactive?: boolean;
}

export interface MarkerLayer extends BaseLayer {
  type: 'marker';
  lat: number;
  lon: number;

  text: string;

  className: string;

  rotateDeg?: number;

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
