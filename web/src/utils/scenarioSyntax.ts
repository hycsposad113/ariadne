import type { SyntaxContextMode, SyntaxContextResponse, SyntaxContextSegment } from './syntaxContext';
export type ComparisonView = 'before' | 'after' | 'diff';
export interface ScenarioSyntaxResult {
  status: string;
  mode: SyntaxContextMode;
  radius_m: number;
  extract_buffer_m: number;
  limitations: string[];
  legend_breaks: SyntaxContextResponse['legend_breaks'];
  before: { segments: SyntaxContextSegment[]; metrics: Record<string, unknown> } | null;
  after: { segments: SyntaxContextSegment[]; metrics: Record<string, unknown> } | null;
  diff: Array<SyntaxContextSegment & { delta: { nain: number; nach: number } | null; comparison_status: string }>;
  job_id?: string;
  error?: string;
}

export function comparisonContext(result: ScenarioSyntaxResult | null, view: ComparisonView): SyntaxContextResponse | null {
  if (!result || result.status !== 'COMPUTED' || !result.before || !result.after) return null;
  const segments = view === 'diff' ? result.diff.map(r => ({ ...r, nain: r.delta?.nain ?? null, nach: r.delta?.nach ?? null })) : result[view]!.segments;
  return { comparison_view: view, mode: result.mode, radius_m: result.radius_m, distance_m: result.extract_buffer_m,
    reliable_within_m: result.extract_buffer_m-result.radius_m, evidence_level: 'EXPLORATORY',
    limitations: result.limitations.join(' '), attribution: '© OpenStreetMap contributors (ODbL 1.0)',
    legend_breaks: result.legend_breaks, segments, segment_count: segments.length };
}
