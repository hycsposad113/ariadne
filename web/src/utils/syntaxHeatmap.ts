/**
 * Syntax Heatmap classification and palette utilities (PD-21).
 *
 * Implements:
 * 1. Quintile breaks (20%, 40%, 60%, 80%) partitioning computed segments into 5 equal bins:
 *    - Very Low (0% - 20%)
 *    - Low (20% - 40%)
 *    - Medium (40% - 60%)
 *    - High (60% - 80%)
 *    - Very High (80% - 100%)
 * 2. depthmapX cold-to-hot palette (Blue -> Cyan -> Green -> Orange -> Red).
 * 3. Explicit uncomputed/excluded handling as gray dashed lines (#64748b, [4, 4]),
 *    never painted as the coldest color.
 */

export type SyntaxQuintileRank = 'very_low' | 'low' | 'medium' | 'high' | 'very_high';

export interface QuintileRange {
  rank: SyntaxQuintileRank;
  label: string;
  min: number;
  max: number;
  color: string;
  count: number;
  percentage: number;
}

export interface SegmentStyle {
  strokeColor: string;
  lineDash: number[];
  lineWidth: number;
  isUncomputed: boolean;
  label: string;
}

export const SYNTAX_PALETTE: Record<SyntaxQuintileRank, { color: string; label: string }> = {
  very_low: { color: '#1d4ed8', label: 'Very Low' },   // Classic depthmapX deep blue
  low: { color: '#06b6d4', label: 'Low' },             // Cyan
  medium: { color: '#10b981', label: 'Medium' },       // Green
  high: { color: '#f59e0b', label: 'High' },           // Amber / Orange
  very_high: { color: '#dc2626', label: 'Very High' }, // Red
};

export const UNCOMPUTED_STYLE = {
  color: '#64748b',
  lineDash: [4, 4],
  label: 'Uncomputed / Excluded',
};

/**
 * Calculates quintile thresholds (q20, q40, q60, q80) from an array of values.
 */
export function calculateQuintileBreaks(values: number[]): [number, number, number, number] {
  const finite = values.filter((v) => typeof v === 'number' && Number.isFinite(v));
  if (finite.length === 0) {
    return [0, 0, 0, 0];
  }
  const sorted = [...finite].sort((a, b) => a - b);
  const n = sorted.length;

  const quantile = (p: number): number => {
    const pos = (n - 1) * p;
    const base = Math.floor(pos);
    const rest = pos - base;
    if (sorted[base + 1] !== undefined) {
      return sorted[base] + rest * (sorted[base + 1] - sorted[base]);
    }
    return sorted[base];
  };

  return [quantile(0.2), quantile(0.4), quantile(0.6), quantile(0.8)];
}

export interface SyntaxHeatmapClassification {
  hasData: boolean;
  min: number;
  max: number;
  breaks: [number, number, number, number];
  ranges: QuintileRange[];
  classify: (value: number | undefined | null) => SegmentStyle;
}

/**
 * Builds a quintile classifier for a given record of segment values or array of numbers.
 */
export function buildSyntaxHeatmapClassification(
  segmentValues: Record<string, number> | number[] | undefined | null,
): SyntaxHeatmapClassification {
  const rawValues = Array.isArray(segmentValues)
    ? segmentValues
    : Object.values(segmentValues || {});
  const validValues = rawValues.filter((v): v is number => typeof v === 'number' && Number.isFinite(v));

  if (validValues.length === 0) {
    return {
      hasData: false,
      min: 0,
      max: 0,
      breaks: [0, 0, 0, 0],
      ranges: [],
      classify: () => ({
        strokeColor: UNCOMPUTED_STYLE.color,
        lineDash: UNCOMPUTED_STYLE.lineDash,
        lineWidth: 1.5,
        isUncomputed: true,
        label: UNCOMPUTED_STYLE.label,
      }),
    };
  }

  const sorted = [...validValues].sort((a, b) => a - b);
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  const breaks = calculateQuintileBreaks(sorted);
  const [q20, q40, q60, q80] = breaks;

  // Count items per bracket
  let cVeryLow = 0;
  let cLow = 0;
  let cMedium = 0;
  let cHigh = 0;
  let cVeryHigh = 0;

  for (const v of sorted) {
    if (v <= q20) cVeryLow++;
    else if (v <= q40) cLow++;
    else if (v <= q60) cMedium++;
    else if (v <= q80) cHigh++;
    else cVeryHigh++;
  }

  const total = sorted.length;
  const pct = (c: number) => (total > 0 ? (c / total) * 100 : 0);

  const ranges: QuintileRange[] = [
    {
      rank: 'very_low',
      label: 'Very Low (0-20%)',
      min,
      max: q20,
      color: SYNTAX_PALETTE.very_low.color,
      count: cVeryLow,
      percentage: pct(cVeryLow),
    },
    {
      rank: 'low',
      label: 'Low (20-40%)',
      min: q20,
      max: q40,
      color: SYNTAX_PALETTE.low.color,
      count: cLow,
      percentage: pct(cLow),
    },
    {
      rank: 'medium',
      label: 'Medium (40-60%)',
      min: q40,
      max: q60,
      color: SYNTAX_PALETTE.medium.color,
      count: cMedium,
      percentage: pct(cMedium),
    },
    {
      rank: 'high',
      label: 'High (60-80%)',
      min: q60,
      max: q80,
      color: SYNTAX_PALETTE.high.color,
      count: cHigh,
      percentage: pct(cHigh),
    },
    {
      rank: 'very_high',
      label: 'Very High (80-100%)',
      min: q80,
      max,
      color: SYNTAX_PALETTE.very_high.color,
      count: cVeryHigh,
      percentage: pct(cVeryHigh),
    },
  ];

  const classify = (value: number | undefined | null): SegmentStyle => {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      return {
        strokeColor: UNCOMPUTED_STYLE.color,
        lineDash: UNCOMPUTED_STYLE.lineDash,
        lineWidth: 1.5,
        isUncomputed: true,
        label: UNCOMPUTED_STYLE.label,
      };
    }

    let color: string;
    let rankLabel: string;

    if (value <= q20) {
      color = SYNTAX_PALETTE.very_low.color;
      rankLabel = 'Very Low';
    } else if (value <= q40) {
      color = SYNTAX_PALETTE.low.color;
      rankLabel = 'Low';
    } else if (value <= q60) {
      color = SYNTAX_PALETTE.medium.color;
      rankLabel = 'Medium';
    } else if (value <= q80) {
      color = SYNTAX_PALETTE.high.color;
      rankLabel = 'High';
    } else {
      color = SYNTAX_PALETTE.very_high.color;
      rankLabel = 'Very High';
    }

    return {
      strokeColor: color,
      lineDash: [],
      lineWidth: 2.5,
      isUncomputed: false,
      label: rankLabel,
    };
  };

  return {
    hasData: true,
    min,
    max,
    breaks,
    ranges,
    classify,
  };
}
