import { planImport } from './shapes-import';

const HEADER = 'stop_id,offset_m,verdict,note,closest_shape_m,has_osm';

describe('planImport', () => {
  const known = new Set(['f1', 'f2', 'f3', 'f4']);

  it('plans a PUT for every row with a verdict or a note', () => {
    const csv = [
      HEADER,
      'f1,83.2,on_route,,4.1,1',
      'f2,60,,"off, the road ""maybe""",,0',
      'f3,51,,,12,0',
    ].join('\n');
    const plan = planImport(csv, known, 'ana');
    expect(plan.skipped).toBe(1);
    expect(plan.requests).toEqual([
      { stopId: 'f1', body: { verdict: 'on_route', note: '', rater: 'ana' } },
      { stopId: 'f2', body: { verdict: null, note: 'off, the road "maybe"', rater: 'ana' } },
    ]);
  });

  it('skips stops that are not in the check', () => {
    const plan = planImport(`${HEADER}\nzzz,1,unclear,x,1,0\nf4,1,unclear,,1,0`, known, null);
    expect(plan.skipped).toBe(1);
    expect(plan.requests.map((r) => r.stopId)).toEqual(['f4']);
    expect(plan.requests[0].body.rater).toBeNull();
  });

  it('drops an unknown verdict but keeps the note; skips it without one', () => {
    const plan = planImport(`${HEADER}\nf1,1,maybe,hm,1,0\nf2,1,maybe,,1,0`, known, null);
    expect(plan.requests).toEqual([
      { stopId: 'f1', body: { verdict: null, note: 'hm', rater: null } },
    ]);
    expect(plan.skipped).toBe(1);
  });

  it('handles newlines inside a quoted note and CRLF files', () => {
    const csv = `${HEADER}\r\nf1,1,off_route,"two\nlines",1,0\r\n`;
    expect(planImport(csv, known, null).requests[0].body.note).toBe('two\nlines');
  });

  it('plans nothing for an empty file', () => {
    expect(planImport('', known, null)).toEqual({ requests: [], skipped: 0 });
  });
});
