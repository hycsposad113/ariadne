import { expect, it } from 'vitest';
import { formatFar, formatPercentage } from './displayMetrics';
it('rounds FAR to two decimals and renders proportions as percentages', () => {
 expect(formatFar(0.7644361027674244)).toBe('0.76');
 expect(formatFar(2.2)).toBe('2.20');
 expect(formatPercentage(0.35678)).toBe('35.7%');
 expect(formatPercentage(0)).toBe('0.0%');
 expect(formatPercentage(1)).toBe('100.0%');
});
