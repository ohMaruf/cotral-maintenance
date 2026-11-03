export interface ViewState {
  scale: number;
  /** Translation in px, relative to the stage centre. */
  x: number;
  y: number;
}

export interface Size {
  w: number;
  h: number;
}

export const MIN_SCALE = 1;
export const MAX_SCALE = 8;
export const IDENTITY: ViewState = { scale: 1, x: 0, y: 0 };

/** Keeps the image from being dragged away: at scale 1 there is nothing to pan. */
export function clampView(view: ViewState, size: Size): ViewState {
  const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, view.scale));
  const maxX = (size.w * (scale - 1)) / 2;
  const maxY = (size.h * (scale - 1)) / 2;
  return {
    scale,
    x: Math.min(maxX, Math.max(-maxX, view.x)),
    y: Math.min(maxY, Math.max(-maxY, view.y)),
  };
}

/**
 * Multiplies the scale by `factor` keeping the content point under (cx, cy)
 * fixed. (cx, cy) is relative to the stage centre; the transform origin is the centre.
 */
export function zoomAt(
  view: ViewState,
  factor: number,
  cx: number,
  cy: number,
  size: Size,
): ViewState {
  const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, view.scale * factor));
  const ratio = scale / view.scale;
  return clampView({ scale, x: cx - (cx - view.x) * ratio, y: cy - (cy - view.y) * ratio }, size);
}

export function panBy(view: ViewState, dx: number, dy: number, size: Size): ViewState {
  return clampView({ ...view, x: view.x + dx, y: view.y + dy }, size);
}
