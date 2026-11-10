import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import * as L from 'leaflet';
import { LatLon } from '../../core/api/api.types';
import { ESRI_TILES, GeoMap, OSM_TILES, createLeafletLayer } from './geo-map';
import { MapLayer } from './map-layers';

@Component({
  imports: [GeoMap],
  template: `<app-geo-map
    [layers]="layers()"
    [bounds]="bounds()"
    (layerClick)="clicked.push($event)"
  />`,
})
class Host {
  readonly layers = signal<MapLayer[]>([]);
  readonly bounds = signal<LatLon[] | null>(null);
  readonly clicked: string[] = [];
}

const pin = (id: string, text: string, extra: Partial<MapLayer> = {}): MapLayer =>
  ({
    type: 'marker',
    id,
    lat: 41.9,
    lon: 12.5,
    text,
    className: 'pin-gtfs',
    ...extra,
  }) as MapLayer;

describe('GeoMap', () => {
  let fixture: ComponentFixture<Host>;
  let el: HTMLElement;

  async function settle(): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  beforeEach(async () => {
    fixture = TestBed.createComponent(Host);
    el = fixture.nativeElement;
    await settle();
  });

  it('creates a Leaflet map with a layers control and a metric scale', () => {
    expect(el.querySelector('.leaflet-container')).not.toBeNull();
    expect(el.querySelector('.leaflet-control-layers')).not.toBeNull();
    const scale = el.querySelector('.leaflet-control-scale');
    expect(scale?.querySelector('.leaflet-control-scale-line')).not.toBeNull();
    expect(el.querySelector('.leaflet-control-attribution')?.textContent).toContain(
      'Imagery © Esri',
    );
    const labels = [...el.querySelectorAll('.leaflet-control-layers-base label')].map((l) =>
      l.textContent?.trim(),
    );
    expect(labels).toEqual(['Satellite (Esri)', 'Streets (OSM)']);
    expect(ESRI_TILES).toContain('World_Imagery/MapServer/tile/{z}/{y}/{x}');
    expect(OSM_TILES).toBe('https://tile.openstreetmap.org/{z}/{x}/{y}.png');
  });

  it('draws the layers it is given and replaces them when they change', async () => {
    fixture.componentInstance.layers.set([
      pin('a', 'G'),
      {
        type: 'polyline',
        id: 'l',
        points: [
          [41.9, 12.5],
          [41.91, 12.51],
        ],
        color: '#fff',
      },
    ]);
    await settle();
    expect(el.querySelectorAll('.geo-marker')).toHaveLength(1);
    expect(el.querySelector('.geo-marker')?.textContent).toBe('G');
    expect(el.querySelectorAll('path.leaflet-interactive, path')).not.toHaveLength(0);

    fixture.componentInstance.layers.set([pin('b', 'V'), pin('c', 'P')]);
    await settle();
    expect([...el.querySelectorAll('.geo-marker')].map((m) => m.textContent)).toEqual(['V', 'P']);
  });

  it('reports clicks on interactive layers only', async () => {
    fixture.componentInstance.layers.set([
      pin('plain', 'G'),
      pin('photo-2', '2', { interactive: true }),
    ]);
    await settle();
    const [plain, photo] = [...el.querySelectorAll<HTMLElement>('.geo-marker')];
    plain.click();
    photo.click();
    expect(fixture.componentInstance.clicked).toEqual(['photo-2']);
  });

  it('fits new bounds without failing', async () => {
    fixture.componentInstance.bounds.set([
      [41.9, 12.5],
      [41.91, 12.51],
    ]);
    await settle();
    expect(el.querySelector('.leaflet-container')).not.toBeNull();
  });

  it('tears the map down on destroy', async () => {
    const container = el.querySelector('.leaflet-container')!;
    fixture.destroy();
    expect(container.querySelector('.leaflet-pane')).toBeNull();
  });
});

const noop = (): void => undefined;

describe('createLeafletLayer', () => {
  it('shows tooltips as text, never as HTML', () => {
    const layer = createLeafletLayer(
      pin('a', 'G', { tooltip: '<img src=x onerror=alert(1)>' }),
      noop,
    );
    const content = layer.getTooltip()!.getContent() as HTMLElement;
    expect(content.textContent).toBe('<img src=x onerror=alert(1)>');
    expect(content.querySelector('img')).toBeNull();
  });

  it('rotates and colours a marker', () => {
    const layer = createLeafletLayer(
      pin('a', '➤', { rotateDeg: 45, color: '#4285f4', size: 14 }),
      noop,
    ) as L.Marker;
    const html = layer.options.icon!.options as L.DivIconOptions;
    const node = html.html as HTMLElement;
    expect(node.style.transform).toBe('rotate(45deg)');
    expect(node.style.color).toBeTruthy();
    expect(node.style.width).toBe('14px');
  });

  it('builds polygons and polylines with the given style', () => {
    const line = createLeafletLayer(
      {
        type: 'polyline',
        id: 'l',
        points: [
          [0, 0],
          [1, 1],
        ],
        color: '#abc',
        weight: 4,
        dashArray: '4 4',
      },
      noop,
    ) as L.Polyline;
    expect(line.options).toMatchObject({ color: '#abc', weight: 4, dashArray: '4 4' });
    const poly = createLeafletLayer(
      {
        type: 'polygon',
        id: 'p',
        points: [
          [0, 0],
          [1, 1],
          [0, 1],
        ],
        color: '#abc',
        fillOpacity: 0.3,
      },
      noop,
    ) as L.Polygon;
    expect(poly.options.fillOpacity).toBe(0.3);
  });
});
