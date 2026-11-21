import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { LucideChevronLeft, LucideChevronRight, LucideX, LucideZoomIn, LucideZoomOut } from '@lucide/angular';
import { Photo } from '../../core/api/api.types';
import { formatDistance, formatHeading } from '../../shared/lib/format';
import { IDENTITY, Size, ViewState, panBy, zoomAt } from './zoom';

export interface PhotoViewerData {
  photos: Photo[];
  index: number;
  stopName: string;
}

const BUTTON_ZOOM = 1.5;
const DOUBLE_CLICK_SCALE = 3;

@Component({
  selector: 'app-photo-viewer',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideChevronLeft, LucideChevronRight, LucideX, LucideZoomIn, LucideZoomOut],
  templateUrl: './photo-viewer.html',
  styleUrl: './photo-viewer.scss',
})
export class PhotoViewer {
  protected readonly data = inject<PhotoViewerData>(DIALOG_DATA);
  private readonly ref = inject<DialogRef<void, PhotoViewer>>(DialogRef);
  private readonly stage = viewChild.required<ElementRef<HTMLElement>>('stage');

  protected readonly index = signal(clampIndex(this.data.index, this.data.photos.length));
  protected readonly view = signal<ViewState>(IDENTITY);
  protected readonly dragging = signal(false);

  protected readonly photo = computed(() => this.data.photos[this.index()]);
  protected readonly distance = computed(() => formatDistance(this.photo().distance_m));
  protected readonly heading = computed(() => formatHeading(this.photo().heading));
  protected readonly transform = computed(() => {
    const v = this.view();
    return `translate(${v.x}px, ${v.y}px) scale(${v.scale})`;
  });
  protected readonly zoomPercent = computed(() => Math.round(this.view().scale * 100));

  private readonly pointers = new Map<number, { x: number; y: number }>();
  private pinchDistance = 0;

  constructor() {
    const sub = this.ref.keydownEvents.subscribe((e) => this.onKey(e));
    inject(DestroyRef).onDestroy(() => sub.unsubscribe());
  }

  protected close(): void {
    this.ref.close();
  }

  protected select(i: number): void {
    if (i < 0 || i >= this.data.photos.length || i === this.index()) return;
    this.index.set(i);
    this.reset();
  }

  protected step(delta: number): void {
    this.select(this.index() + delta);
  }

  protected zoomIn(): void {
    this.zoomBy(BUTTON_ZOOM, 0, 0);
  }

  protected zoomOut(): void {
    this.zoomBy(1 / BUTTON_ZOOM, 0, 0);
  }

  protected reset(): void {
    this.view.set(IDENTITY);
  }

  protected onWheel(event: WheelEvent): void {
    event.preventDefault();
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 400 : 1;
    const { x, y } = this.fromCentre(event.clientX, event.clientY);
    this.zoomBy(Math.exp(-event.deltaY * unit * 0.0018), x, y);
  }

  protected onDoubleClick(event: MouseEvent): void {
    if (this.view().scale > 1) {
      this.reset();
    } else {
      const { x, y } = this.fromCentre(event.clientX, event.clientY);
      this.zoomBy(DOUBLE_CLICK_SCALE, x, y);
    }
  }

  protected onPointerDown(event: PointerEvent): void {
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    this.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    this.dragging.set(true);
    if (this.pointers.size === 2) this.pinchDistance = this.currentPinch().distance;
  }

  protected onPointerMove(event: PointerEvent): void {
    const prev = this.pointers.get(event.pointerId);
    if (!prev) return;
    const next = { x: event.clientX, y: event.clientY };
    if (this.pointers.size === 1) {
      this.view.update((v) => panBy(v, next.x - prev.x, next.y - prev.y, this.size()));
      this.pointers.set(event.pointerId, next);
    } else if (this.pointers.size === 2) {
      const before = this.currentPinch();
      this.pointers.set(event.pointerId, next);
      const after = this.currentPinch();
      const mid = this.fromCentre(after.x, after.y);
      if (this.pinchDistance > 0 && after.distance > 0) {
        this.zoomBy(after.distance / this.pinchDistance, mid.x, mid.y);
      }
      this.view.update((v) => panBy(v, after.x - before.x, after.y - before.y, this.size()));
      this.pinchDistance = after.distance;
    }
  }

  protected onPointerUp(event: PointerEvent): void {
    this.pointers.delete(event.pointerId);
    this.pinchDistance = 0;
    if (this.pointers.size === 0) this.dragging.set(false);
  }

  private onKey(event: KeyboardEvent): void {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const handlers: Record<string, () => void> = {
      '+': () => this.zoomIn(),
      '=': () => this.zoomIn(),
      '-': () => this.zoomOut(),
      _: () => this.zoomOut(),
      '0': () => this.reset(),
      ArrowLeft: () => this.step(-1),
      ArrowRight: () => this.step(1),
    };
    const handler = handlers[event.key];
    if (!handler) return;
    event.preventDefault();
    handler();
  }

  private zoomBy(factor: number, cx: number, cy: number): void {
    this.view.update((v) => zoomAt(v, factor, cx, cy, this.size()));
  }

  private size(): Size {
    const el = this.stage().nativeElement;
    return { w: el.clientWidth, h: el.clientHeight };
  }

  private fromCentre(clientX: number, clientY: number): { x: number; y: number } {
    const r = this.stage().nativeElement.getBoundingClientRect();
    return { x: clientX - (r.left + r.width / 2), y: clientY - (r.top + r.height / 2) };
  }

  private currentPinch(): { x: number; y: number; distance: number } {
    const [a, b] = [...this.pointers.values()];
    return {
      x: (a.x + b.x) / 2,
      y: (a.y + b.y) / 2,
      distance: Math.hypot(a.x - b.x, a.y - b.y),
    };
  }
}

function clampIndex(i: number, length: number): number {
  return Math.min(Math.max(0, i), Math.max(0, length - 1));
}
