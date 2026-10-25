import { SYNTAX_PALETTE, UNCOMPUTED_STYLE, type SegmentStyle } from './syntaxHeatmap';

export type SyntaxContextMode = 'pedestrian' | 'bicycle' | 'motor_vehicle';
export type SyntaxContextMetric = 'nain' | 'nach';

export interface SyntaxContextSegment {
  id: string;
  source_line_id?: string;
  coordinates: [number, number][];
  distance_to_site_m: number;
  inside_site: boolean;
  boundary_effect_risk: boolean;
  nain: number | null;
  nach: number | null;
}

export interface SyntaxContextReadiness {
  mode: string;
  radius_m: number;
  status: string;
  reason: string;
  manifest_sha256: string;
  formal_result: boolean;
  bound_manifest_sha256: string;
  manifest_binding: 'SHIPPED' | 'UNBOUND_MANIFEST';
}

export interface SyntaxContextResponse {
  comparison_metric?: SyntaxContextMetric;
  comparison_delta_max?: Record<SyntaxContextMetric, number>;
  comparison_view?: "before" | "after" | "diff";
  mode: SyntaxContextMode;
  radius_m: number;
  distance_m: number;
  reliable_within_m: number;
  evidence_level: string;
  limitations: string;
  attribution: string;
  segment_count: number;
  legend_breaks: {
    nain: [number, number, number, number, number, number];
    nach: [number, number, number, number, number, number];
  };
  segments: SyntaxContextSegment[];
  readiness?: SyntaxContextReadiness;
}

export function syntaxContextBadgeStatus(data: Pick<SyntaxContextResponse, 'readiness' | 'evidence_level'>): string {
  return data.readiness?.status || data.evidence_level || 'EXPLORATORY';
}

export interface ContextHeatmapClassification {
  breaks: [number, number, number, number, number, number];
  classify: (value: number | undefined | null) => SegmentStyle;
  ranges: Array<{
    label: string;
    min: number;
    max: number;
    color: string;
  }>;
}

export function buildClassificationFromBreaks(
  breaks: [number, number, number, number, number, number] | number[],
): ContextHeatmapClassification {
  const [min, q20, q40, q60, q80, max] = breaks.length === 6 ? breaks : [0, 0, 0, 0, 0, 0];
  const ranges = [
    { label: 'Very Low (0-20%)', min, max: q20, color: SYNTAX_PALETTE.very_low.color },
    { label: 'Low (20-40%)', min: q20, max: q40, color: SYNTAX_PALETTE.low.color },
    { label: 'Medium (40-60%)', min: q40, max: q60, color: SYNTAX_PALETTE.medium.color },
    { label: 'High (60-80%)', min: q60, max: q80, color: SYNTAX_PALETTE.high.color },
    { label: 'Very High (80-100%)', min: q80, max, color: SYNTAX_PALETTE.very_high.color },
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
      lineWidth: 1.5,
      isUncomputed: false,
      label: rankLabel,
    };
  };

  return {
    breaks: [min, q20, q40, q60, q80, max],
    classify,
    ranges,
  };
}

export function hexToRgba(hex: string, alpha: number): string {
  const clean = hex.replace('#', '');
  if (clean.length === 6) {
    const r = parseInt(clean.substring(0, 2), 16);
    const g = parseInt(clean.substring(2, 4), 16);
    const b = parseInt(clean.substring(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  return hex;
}

const API_BASE = (import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8789').replace(/\/$/, '');
const PROJECT_ID = 'rotterdam-m4h-pilot-project';

export async function fetchSyntaxContext(
  mode: SyntaxContextMode,
  distanceM: number,
  apiBase: string = API_BASE,
  projectId: string = PROJECT_ID,
): Promise<SyntaxContextResponse> {
  const capabilities = await fetch(`${apiBase}/api/v1/projects/${projectId}/syntax/context/capabilities`);
  if (capabilities.ok) {
    const capability = await capabilities.json();
    if (capability.enabled === false) throw new Error(capability.reason_zh || '此執行環境尚未提供空間語法背景資料。');
  }
  const url = `${apiBase}/api/v1/projects/${projectId}/syntax/context?mode=${mode}&distance_m=${distanceM}`;
  const res = await fetch(url);
  if (!res.ok) {
    let detail = '';
    try {
      const body = await res.json();
      detail = body.detail || '';
    } catch {
      // ignore
    }
    throw new Error(detail || `SYNTAX_CONTEXT_REQUEST_FAILED_${res.status}`);
  }
  const data = await res.json();
  if (!data || !Array.isArray(data.segments)) {
    throw new Error('SYNTAX_CONTEXT_INVALID_PAYLOAD');
  }
  return data as SyntaxContextResponse;
}


export function classifyContextValue(data: SyntaxContextResponse, metric: SyntaxContextMetric, value: number | null) {
  if (data.comparison_view !== 'diff') return buildClassificationFromBreaks(data.legend_breaks[metric]).classify(value);
  const missing = value === null || !Number.isFinite(value);
  const max = data.comparison_delta_max?.[metric] ?? 1;
  const intensity = Math.min(1, Math.abs(value ?? 0) / (max || 1));
  const target = (value ?? 0) < 0 ? [59, 130, 246] : [239, 68, 68];
  const neutral = [203, 213, 225];
  const color = '#' + neutral.map((v, i) => Math.round(v + (target[i] - v) * intensity).toString(16).padStart(2, '0')).join('');
  return { strokeColor: missing ? '#64748b' : color,
    lineDash: missing ? [3, 3] : [], lineWidth: 2, isUncomputed: missing,
    label: missing ? 'No comparable segment' : value > 0 ? 'Increase' : value < 0 ? 'Decrease' : 'Unchanged' };
}
