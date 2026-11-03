import { ScoreMap } from '../../core/api/api.types';
import { modelAgreement } from './agreement';

const s = (v?: number): ScoreMap => (v === undefined ? {} : { clef: { requires_maintenance: v } });

describe('modelAgreement', () => {
  it('agrees when the chosen side has the higher overall score', () => {
    expect(modelAgreement(s(3), s(1), 'clef', 'left')).toEqual({
      kind: 'agrees',
      left: 3,
      right: 1,
    });
    expect(modelAgreement(s(1), s(3), 'clef', 'right').kind).toBe('agrees');
  });

  it('disagrees when the chosen side has the lower score', () => {
    expect(modelAgreement(s(3), s(1), 'clef', 'right').kind).toBe('disagrees');
  });

  it('reports ties, skips and missing scores', () => {
    expect(modelAgreement(s(2), s(2), 'clef', 'left').kind).toBe('tie');
    expect(modelAgreement(s(3), s(1), 'clef', 'skip').kind).toBe('no-pick');
    expect(modelAgreement(s(), s(1), 'clef', 'left').kind).toBe('no-score');
    expect(modelAgreement(s(3), s(1), 'other', 'left').kind).toBe('no-score');
  });
});
