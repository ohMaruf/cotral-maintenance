import { Photo } from '../../core/api/api.types';

export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–';
  return value.toFixed(2);
}

export function formatDistance(meters: number | null): string | null {
  return meters === null ? null : `${Math.round(meters)} m`;
}

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];

export function formatHeading(degrees: number | null): string | null {
  if (degrees === null) return null;
  const norm = ((degrees % 360) + 360) % 360;
  return `${Math.round(norm)}° ${COMPASS[Math.round(norm / 45) % 8]}`;
}

export function formatCoordinates(lat: number, lon: number): string {
  return `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
}

export function mapsUrl(lat: number, lon: number): string {
  return `https://www.google.com/maps?q=${lat},${lon}`;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function formatImageryDate(date: string | null): string {
  if (!date) return 'unknown';
  const m = /^(\d{4})-(\d{2})/.exec(date);
  const month = m ? MONTHS[Number(m[2]) - 1] : undefined;
  return m && month ? `${month} ${m[1]}` : date;
}

export function photoDetails(photo: Photo): string[] {
  return [formatDistance(photo.distance_m), formatHeading(photo.heading)].filter(
    (p): p is string => p !== null,
  );
}
