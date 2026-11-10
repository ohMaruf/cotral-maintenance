import { argRows, checklistRows, eventKindInfo, resultText, timelineLine } from './event-kind';
import { event } from './explore-testing';

describe('eventKindInfo', () => {
  it('knows thoughts, tools and refused calls', () => {
    expect(eventKindInfo('thought')).toMatchObject({
      label: 'Thought',
      thought: true,
      danger: false,
    });
    expect(eventKindInfo('look')).toMatchObject({ label: 'Look', thought: false, danger: false });
    expect(eventKindInfo('sweep').label).toBe('Sweep');
    expect(eventKindInfo('zoom').label).toBe('Zoom');
    expect(eventKindInfo('look_from').label).toBe('Look from another panorama');
    expect(eventKindInfo('answer_checklist').label).toBe('Answer checklist');
    expect(eventKindInfo('tool_error')).toMatchObject({ label: 'Refused call', danger: true });
  });

  it('marks a failed call as danger and passes unknown kinds through', () => {
    expect(eventKindInfo('look', 'no panorama').danger).toBe(true);
    expect(eventKindInfo('some_new_tool')).toEqual({
      label: 'some new tool',
      glyph: '?',
      thought: false,
      danger: false,
    });
  });
});

describe('argRows', () => {
  it('lists arguments, dropping null ones and stringifying values', () => {
    expect(argRows({ from_m: 5, toward: 'forward', target_m: null, tags: ['a'] })).toEqual([
      { key: 'from_m', value: '5' },
      { key: 'toward', value: 'forward' },
      { key: 'tags', value: '["a"]' },
    ]);
  });

  it('gives no rows for missing or non-object requests', () => {
    expect(argRows(null)).toEqual([]);
    expect(argRows('text')).toEqual([]);
    expect(argRows([1])).toEqual([]);
    expect(argRows({})).toEqual([]);
  });
});

describe('text helpers', () => {
  it('flattens whitespace for the timeline line', () => {
    expect(timelineLine(event(1, { summary: ' a\n  b ' }))).toBe('a b');
  });

  it('returns the result text, as is for strings and as JSON otherwise', () => {
    expect(resultText(event(1, { raw: { request: {}, response: 'full\ntext' } }))).toBe(
      'full\ntext',
    );
    expect(resultText(event(1, { raw: { request: {}, response: { a: 1 } } }))).toBe(
      '{\n  "a": 1\n}',
    );
    expect(resultText(event(1, { raw: { request: {}, response: null } }))).toBe('');
  });
});

describe('checklistRows', () => {
  it('puts yes first, then unsure, then no, keeping the order within an answer', () => {
    expect(
      checklistRows({ a: 'no', b: 'unsure', c: 'yes', d: 'no', e: 'maybe', f: 'yes' }).map(
        (r) => r.feature,
      ),
    ).toEqual(['c', 'f', 'b', 'a', 'd', 'e']);
    expect(checklistRows({})).toEqual([]);
  });
});
