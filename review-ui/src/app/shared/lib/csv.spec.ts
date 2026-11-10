import { csvField, parseCsv, parseCsvRecords } from './csv';

describe('parseCsv', () => {
  it('parses plain rows with LF and CRLF line endings', () => {
    expect(parseCsv('a,b\n1,2\r\n3,4\n')).toEqual([
      ['a', 'b'],
      ['1', '2'],
      ['3', '4'],
    ]);
  });

  it('keeps empty fields, including a trailing one', () => {
    expect(parseCsv('a,,c,\n,,')).toEqual([
      ['a', '', 'c', ''],
      ['', '', ''],
    ]);
  });

  it('handles quotes with commas, escaped quotes and newlines inside', () => {
    const text = 'id,note\nf1,"hello, ""world""\nsecond line"\nf2,plain';
    expect(parseCsv(text)).toEqual([
      ['id', 'note'],
      ['f1', 'hello, "world"\nsecond line'],
      ['f2', 'plain'],
    ]);
  });

  it('parses an empty quoted field and a quote-only escape', () => {
    expect(parseCsv('a,"",""""')).toEqual([['a', '', '"']]);
  });

  it('skips blank lines and a BOM, and returns nothing for empty input', () => {
    expect(parseCsv('﻿a,b\n\n1,2\n\n')).toEqual([
      ['a', 'b'],
      ['1', '2'],
    ]);
    expect(parseCsv('')).toEqual([]);
  });

  it('keeps a quoted blank line that is a real row of one empty field', () => {
    expect(parseCsv('a\n""\nb')).toEqual([['a'], [''], ['b']]);
  });
});

describe('parseCsvRecords', () => {
  it('keys rows by the header and pads short rows', () => {
    const text =
      'stop_id,offset_m,verdict,note,closest_shape_m,has_osm\nf1,83.2,on_route,"a, b",4.1,1\nf2,60';
    expect(parseCsvRecords(text)).toEqual([
      {
        stop_id: 'f1',
        offset_m: '83.2',
        verdict: 'on_route',
        note: 'a, b',
        closest_shape_m: '4.1',
        has_osm: '1',
      },
      {
        stop_id: 'f2',
        offset_m: '60',
        verdict: '',
        note: '',
        closest_shape_m: '',
        has_osm: '',
      },
    ]);
  });

  it('is empty without a header', () => {
    expect(parseCsvRecords('')).toEqual([]);
  });
});

describe('csvField', () => {
  it('quotes only when needed and doubles quotes', () => {
    expect(csvField('plain')).toBe('plain');
    expect(csvField('a,b')).toBe('"a,b"');
    expect(csvField('say "hi"')).toBe('"say ""hi"""');
    expect(parseCsv(csvField('x\n"y",z'))).toEqual([['x\n"y",z']]);
  });
});
