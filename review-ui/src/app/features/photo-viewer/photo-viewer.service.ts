import { Dialog } from '@angular/cdk/dialog';
import { Injectable, inject } from '@angular/core';
import { Photo } from '../../core/api/api.types';

@Injectable({ providedIn: 'root' })
export class PhotoViewerService {
  private readonly dialog = inject(Dialog);

  async open(photos: Photo[], index: number, stopName: string): Promise<void> {
    if (photos.length === 0) return;
    const { PhotoViewer } = await import('./photo-viewer');
    this.dialog.open(PhotoViewer, {
      data: { photos, index, stopName },
      ariaLabel: `Photos of ${stopName}`,
      autoFocus: 'dialog',
      restoreFocus: true,
      width: 'min(96vw, 1100px)',
      height: 'min(94vh, 860px)',
      maxWidth: '96vw',
      panelClass: 'photo-viewer-panel',
      backdropClass: 'photo-viewer-backdrop',
    });
  }
}
