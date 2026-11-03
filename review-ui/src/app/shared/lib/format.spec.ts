import { photo } from '../../testing';
import {
  formatCoordinates,
  formatDistance,
  formatHeading,
  formatImageryDate,
  formatScore,
  mapsUrl,
  photoDetails,
} from './format';

describe('format', () => {
  it('formats scores per kind and shows a dash for missing values', () => {
    expect(formatScore(2, 'level')).toBe('2');
    expect(formatScore(2.44, 'level')).toBe('2.4');
    expect(formatScore(0.8, 'probability')).toBe('0.80');
    expect(formatScore(undefined, 'level')).toBe('–');
    expect(formatScore(null, 'probability')).toBe('–');
  });

  it('formats imagery dates', () => {
    expect(formatImageryDate('2025-06')).toBe('Jun 2025');
    expect(formatImageryDate('2025-06-15')).toBe('Jun 2025');
    expect(formatImageryDate(null)).toBe('unknown');
    expect(formatImageryDate('summer')).toBe('summer');
  });

  it('formats distance and heading with null passthrough', () => {
    expect(formatDistance(23.6)).toBe('24 m');
    expect(formatDistance(null)).toBeNull();
    expect(formatHeading(90)).toBe('90° E');
    expect(formatHeading(-45)).toBe('315° NW');
    expect(formatHeading(359)).toBe('359° N');
    expect(formatHeading(null)).toBeNull();
  });

  it('builds map links and coordinates', () => {
    expect(mapsUrl(41.9, 12.5)).toBe('https://www.google.com/maps?q=41.9,12.5');
    expect(formatCoordinates(41.9, 12.5)).toBe('41.90000, 12.50000');
  });

  it('lists the available photo details', () => {
    expect(photoDetails(photo('a', 1))).toEqual(['24 m', '90° E']);
    expect(photoDetails({ ...photo('a', 1), distance_m: null, heading: null })).toEqual([]);
  });
});
