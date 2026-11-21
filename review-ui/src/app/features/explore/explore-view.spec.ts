import {
  adjacentRun,
  compareVersions,
  groupRuns,
  visibleRuns,
  currentEvent,
  eventOfPhoto,
  orderedEvents,
  parseSeq,
  stepPhotoSeq,
  stepSeq,
} from './explore-view';
import { event, exploration, harness, summary } from './explore-testing';

const events = exploration().event_list;

describe('explore-view', () => {
  it('parses the event param', () => {
    expect(parseSeq('3')).toBe(3);
    expect(parseSeq(undefined)).toBeNull();
    expect(parseSeq('')).toBeNull();
    expect(parseSeq('0')).toBeNull();
    expect(parseSeq('-2')).toBeNull();
    expect(parseSeq('1.5')).toBeNull();
    expect(parseSeq('abc')).toBeNull();
  });

  it('orders events by seq whatever the input order', () => {
    const run = exploration('f1', { event_list: [event(3), event(1), event(2)] });
    expect(orderedEvents(run).map((e) => e.seq)).toEqual([1, 2, 3]);
  });

  it('picks the requested event, else the first', () => {
    expect(currentEvent(events, 4)?.seq).toBe(4);
    expect(currentEvent(events, 99)?.seq).toBe(1);
    expect(currentEvent(events, null)?.seq).toBe(1);
    expect(currentEvent([], 1)).toBeNull();
  });

  it('steps through events and stops at the ends', () => {
    expect(stepSeq(events, events[1], 'next')).toBe(3);
    expect(stepSeq(events, events[1], 'prev')).toBe(1);
    expect(stepSeq(events, events[0], 'prev')).toBeNull();
    expect(stepSeq(events, events[5], 'next')).toBeNull();
    expect(stepSeq(events, events[2], 'first')).toBe(1);
    expect(stepSeq(events, events[2], 'last')).toBe(6);
    expect(stepSeq(events, events[5], 'last')).toBeNull();
    expect(stepSeq([], null, 'next')).toBeNull();
  });

  it('finds the event that took a photo', () => {
    expect(eventOfPhoto(events, 3)?.seq).toBe(3);
    expect(eventOfPhoto(events, 2)?.seq).toBe(1);
    expect(eventOfPhoto(events, 9)).toBeNull();
  });

  it('steps to the next and previous event that took photos', () => {
    expect(stepPhotoSeq(events, events[0], 'next')).toBe(3);
    expect(stepPhotoSeq(events, events[1], 'next')).toBe(3);
    expect(stepPhotoSeq(events, events[1], 'previous')).toBe(1);
    expect(stepPhotoSeq(events, events[3], 'previous')).toBe(3);
    expect(stepPhotoSeq(events, events[2], 'next')).toBeNull();
    expect(stepPhotoSeq(events, events[0], 'previous')).toBeNull();
    expect(stepPhotoSeq([], null, 'next')).toBeNull();
  });

  it('finds the adjacent run, without wrapping', () => {
    const runs = ['a', 'b', 'c'].map((id) => summary(id));
    expect(adjacentRun(runs, 'b', 1)?.run_id).toBe('c');
    expect(adjacentRun(runs, 'b', -1)?.run_id).toBe('a');
    expect(adjacentRun(runs, 'c', 1)).toBeNull();
    expect(adjacentRun(runs, 'a', -1)).toBeNull();
    expect(adjacentRun(runs, null, 1)?.run_id).toBe('a');
    expect(adjacentRun(runs, 'zzz', -1)?.run_id).toBe('c');
    expect(adjacentRun([], 'a', 1)).toBeNull();
  });
});

describe('harness grouping', () => {
  const run = (id: string, version: string | null, outcome = 'found') =>
    summary(id, { outcome, ...(version ? { harness: harness(version) } : {}) });
  const runs = [
    run('a', null),
    run('b', '0.6.0'),
    run('c', '0.10.0', 'not_found'),
    run('d', '0.6.0', 'error'),
    run('e', '0.7'),
  ];

  it('compares versions numerically, newest first, unversioned last', () => {
    expect(['0.6.0', 'unversioned', '0.10.0', '0.7'].sort(compareVersions)).toEqual([
      '0.10.0',
      '0.7',
      '0.6.0',
      'unversioned',
    ]);
    expect(compareVersions('0.7', '0.7.0')).toBe(0);
  });

  it('groups with counts and found totals, keeping the run order inside a group', () => {
    expect(groupRuns(runs).map((g) => [g.version, g.runs.map((r) => r.run_id), g.found])).toEqual([
      ['0.10.0', ['c'], 0],
      ['0.7', ['e'], 1],
      ['0.6.0', ['b', 'd'], 1],
      ['unversioned', ['a'], 1],
    ]);
  });

  it('lists the runs in group order, or of one version', () => {
    expect(visibleRuns(runs, null).map((r) => r.run_id)).toEqual(['c', 'e', 'b', 'd', 'a']);
    expect(visibleRuns(runs, '0.6.0').map((r) => r.run_id)).toEqual(['b', 'd']);
    expect(visibleRuns(runs, '9.9')).toEqual([]);
  });
});
