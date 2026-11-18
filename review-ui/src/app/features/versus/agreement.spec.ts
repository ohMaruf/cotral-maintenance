import { ScoreMap } from '../../core/api/api.types';
import { modelAgreement } from './agreement';

const s = (v?: number): ScoreMap => (v === undefined ? {} : { clef: { condition: v } });

describe('modelAgreement', () => {
  it('agrees when the chosen side has the lower condition', () => {
    expect(modelAgreement(s(0.2), s(0.8), 'clef', 'left')).toEqual({
      kind: 'agrees',
      left: 0.2,
      right: 0.8,
    });
    expect(modelAgreement(s(0.8), s(0.2), 'clef', 'right').kind).toBe('agrees');
  });

  it('disagrees when the chosen side has the higher condition', () => {
    expect(modelAgreement(s(0.2), s(0.8), 'clef', 'right').kind).toBe('disagrees');
    expect(modelAgreement(s(0.8), s(0.2), 'clef', 'left').kind).toBe('disagrees');
  });

  it('reports ties, skips and missing scores', () => {
    expect(modelAgreement(s(0.5), s(0.5), 'clef', 'left').kind).toBe('tie');
    expect(modelAgreement(s(0.2), s(0.8), 'clef', 'skip').kind).toBe('no-pick');
    expect(modelAgreement(s(), s(0.8), 'clef', 'left').kind).toBe('no-score');
    expect(modelAgreement(s(0.2), s(0.8), 'other', 'left').kind).toBe('no-score');
  });
});
