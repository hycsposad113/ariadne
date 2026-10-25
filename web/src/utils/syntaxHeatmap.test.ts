import { describe, it, expect } from 'vitest';
import {
  calculateQuintileBreaks,
  buildSyntaxHeatmapClassification,
  SYNTAX_PALETTE,
  UNCOMPUTED_STYLE,
} from './syntaxHeatmap';

describe('syntaxHeatmap', () => {
  it('calculates quintile breaks correctly for a uniform 0-100 series', () => {
    // 101 values from 0 to 100
    const values = Array.from({ length: 101 }, (_, i) => i);
    const [q20, q40, q60, q80] = calculateQuintileBreaks(values);
    expect(q20).toBeCloseTo(20, 1);
    expect(q40).toBeCloseTo(40, 1);
    expect(q60).toBeCloseTo(60, 1);
    expect(q80).toBeCloseTo(80, 1);
  });

  it('handles empty or non-finite inputs gracefully', () => {
    const classification = buildSyntaxHeatmapClassification([]);
    expect(classification.hasData).toBe(false);
    expect(classification.ranges).toHaveLength(0);
    const style = classification.classify(10);
    expect(style.isUncomputed).toBe(true);
    expect(style.strokeColor).toBe(UNCOMPUTED_STYLE.color);
    expect(style.lineDash).toEqual(UNCOMPUTED_STYLE.lineDash);
  });

  it('classifies uncomputed and excluded values as gray dashed lines, never coldest color', () => {
    const values = { s1: 1.0, s2: 2.0, s3: 3.0, s4: 4.0, s5: 5.0 };
    const classification = buildSyntaxHeatmapClassification(values);

    const uncomputedStyle = classification.classify(undefined);
    expect(uncomputedStyle.isUncomputed).toBe(true);
    expect(uncomputedStyle.strokeColor).toBe('#64748b');
    expect(uncomputedStyle.lineDash).toEqual([4, 4]);
    expect(uncomputedStyle.strokeColor).not.toBe(SYNTAX_PALETTE.very_low.color);

    const nullStyle = classification.classify(null);
    expect(nullStyle.isUncomputed).toBe(true);
    expect(nullStyle.strokeColor).toBe('#64748b');

    const nanStyle = classification.classify(NaN);
    expect(nanStyle.isUncomputed).toBe(true);
    expect(nanStyle.strokeColor).toBe('#64748b');
  });

  it('classifies values across the 5 quintiles to depthmapX colors', () => {
    // 10 values: 1 to 10
    const values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    const classification = buildSyntaxHeatmapClassification(values);

    expect(classification.hasData).toBe(true);
    expect(classification.ranges).toHaveLength(5);

    // Lowest value should be very_low (blue)
    const style1 = classification.classify(1);
    expect(style1.isUncomputed).toBe(false);
    expect(style1.strokeColor).toBe(SYNTAX_PALETTE.very_low.color);
    expect(style1.lineDash).toEqual([]);

    // Highest value should be very_high (red)
    const style10 = classification.classify(10);
    expect(style10.isUncomputed).toBe(false);
    expect(style10.strokeColor).toBe(SYNTAX_PALETTE.very_high.color);
    expect(style10.lineDash).toEqual([]);
  });

  it('partitions counts into approximately 20% bins', () => {
    const values = Array.from({ length: 100 }, (_, i) => i + 1);
    const classification = buildSyntaxHeatmapClassification(values);
    for (const range of classification.ranges) {
      expect(range.count).toBeGreaterThanOrEqual(18);
      expect(range.count).toBeLessThanOrEqual(22);
      expect(range.percentage).toBeGreaterThanOrEqual(18);
      expect(range.percentage).toBeLessThanOrEqual(22);
    }
  });
});
