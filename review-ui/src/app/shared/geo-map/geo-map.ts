import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  ViewEncapsulation,
  afterNextRender,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import * as L from 'leaflet';
import { LatLon } from '../../core/api/api.types';
import { MapLayer } from './map-layers';

export const ESRI_TILES =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
export const OSM_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const MAX_ZOOM = 21;

/** Leaflet layer for one declarative layer; exported for tests. */
export function createLeafletLayer(layer: MapLayer, onClick: (id: string) => void): L.Layer {
  let created: L.Layer;
  switch (layer.type) {
    case 'marker': {
      const size = layer.size ?? 22;
      const el = document.createElement('div');
      el.className = `geo-marker ${layer.className}`;
      el.textContent = layer.text;
      el.style.width = `${size}px`;
      el.style.height = `${size}px`;
      if (layer.color) el.style.color = layer.color;
      if (layer.rotateDeg) el.style.transform = `rotate(${layer.rotateDeg}deg)`;
      created = L.marker([layer.lat, layer.lon], {
        icon: L.divIcon({
          className: 'geo-icon',
          html: el,
          iconSize: [size, size],
          iconAnchor: [size / 2, size / 2],
        }),
        interactive: layer.interactive ?? false,
        keyboard: layer.interactive ?? false,
        title: layer.interactive ? layer.tooltip : undefined,
        zIndexOffset: layer.zIndexOffset ?? 0,
      });
      break;
    }
    case 'polyline':
      created = L.polyline(layer.points, {
        color: layer.color,
        weight: layer.weight ?? 3,
        opacity: layer.opacity ?? 1,
        dashArray: layer.dashArray,
        interactive: layer.interactive ?? layer.tooltip !== undefined,
      });
      break;
    case 'polygon':
      created = L.polygon(layer.points, {
        color: layer.color,
        weight: layer.weight ?? 1,
        opacity: layer.opacity ?? 1,
        fillOpacity: layer.fillOpacity ?? 0.2,
        interactive: layer.interactive ?? false,
      });
      break;
  }
  if (layer.tooltip) {
    // An element, not a string: Leaflet would parse a string as HTML.
    const text = document.createElement('span');
    text.textContent = layer.tooltip;
    created.bindTooltip(text);
  }
  if (layer.interactive) created.on('click', () => onClick(layer.id));
  return created;
}

/**
 * Leaflet map with the Esri satellite (default) and OpenStreetMap basemaps, a layers
 * control and a metric scale. Owns the map lifecycle; callers pass what to draw.
 * The host element needs a height.
 */
@Component({
  selector: 'app-geo-map',
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: '<div #container class="geo-map" role="application" [attr.aria-label]="label()"></div>',
  styleUrl: './geo-map.scss',
})
export class GeoMap {
  readonly layers = input<MapLayer[]>([]);
  /** Points to fit in view whenever this value changes; null leaves the view alone. */
  readonly bounds = input<LatLon[] | null>(null);
  readonly fitPadding = input(40);
  readonly fitMaxZoom = input(19);
  readonly label = input('Map');
  /** Id of an interactive layer that was clicked. */
  readonly layerClick = output<string>();

  private readonly container = viewChild.required<ElementRef<HTMLElement>>('container');
  private readonly ready = signal(false);
  private map: L.Map | null = null;
  private group: L.LayerGroup | null = null;
  private observer: ResizeObserver | null = null;

  constructor() {
    afterNextRender(() => this.create());
    inject(DestroyRef).onDestroy(() => this.destroy());

    effect(() => {
      const layers = this.layers();
      if (!this.ready() || !this.group) return;
      this.group.clearLayers();
      for (const layer of layers) {
        createLeafletLayer(layer, (id) => this.layerClick.emit(id)).addTo(this.group);
      }
    });

    effect(() => {
      const points = this.bounds();
      const padding = this.fitPadding();
      const maxZoom = this.fitMaxZoom();
      if (!this.ready() || !this.map || !points || points.length === 0) return;
      this.map.invalidateSize();
      this.map.fitBounds(L.latLngBounds(points), { padding: [padding, padding], maxZoom });
    });
  }

  private create(): void {
    const el = this.container().nativeElement;
    const map = L.map(el, { maxZoom: MAX_ZOOM, zoomControl: true });
    const satellite = L.tileLayer(ESRI_TILES, {
      maxZoom: MAX_ZOOM,
      maxNativeZoom: 19,
      attribution: 'Imagery © Esri',
    });
    const streets = L.tileLayer(OSM_TILES, {
      maxZoom: MAX_ZOOM,
      maxNativeZoom: 19,
      attribution: '© OpenStreetMap contributors',
    });
    satellite.addTo(map);
    L.control.layers({ 'Satellite (Esri)': satellite, 'Streets (OSM)': streets }).addTo(map);
    L.control.scale({ imperial: false }).addTo(map);
    map.setView([41.9, 12.5], 5); // a view is required before layers are added
    this.group = L.layerGroup().addTo(map);
    this.map = map;
    if (typeof ResizeObserver !== 'undefined') {
      this.observer = new ResizeObserver(() => map.invalidateSize());
      this.observer.observe(el);
    }
    this.ready.set(true);
  }

  private destroy(): void {
    this.observer?.disconnect();
    this.observer = null;
    this.map?.remove();
    this.map = null;
    this.group = null;
  }
}
