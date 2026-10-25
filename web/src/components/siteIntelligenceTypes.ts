export interface FrozenRef {
  id: string;
  revision: number;
  sha256: string;
}

export type AnalysisStatus = 'AVAILABLE' | 'PARTIAL' | 'BLOCKED' | 'NOT_RUN';

export interface Opportunity {
  id: string;
  origin: 'AI_SUGGESTED' | 'DESIGNER_AUTHORED' | 'RULE_SUGGESTED';
  statement: string;
  kind: 'OBSERVED_PROBLEM' | 'CONDITIONAL_HYPOTHESIS' | 'DESIGN_PREFERENCE';
  evidence_refs: FrozenRef[];
  scope_ref: FrozenRef;
  suggested_actions?: string[];
  counterexamples?: string[];
  verification_metric_keys?: string[];
  uncertainties?: string[];
  limitation_codes?: string[];
  designer_questions?: string[];
}

export interface DesignIntent {
  id: string;
  text: string;
  scope_ref: FrozenRef;
  kind: 'PREFERENCE' | 'REQUIRED_FEATURE' | 'AVOID_FEATURE';
  source_opportunity_ids: string[];
  origin: 'AI_SUGGESTED' | 'DESIGNER_AUTHORED' | 'RULE_SUGGESTED';
  priority: number | null;
  version: number;
}

export interface OpportunityRejection {
  opportunity_id: string;
  reason: string;
}

export interface DesignBriefRevision {
  id: string;
  revision: number;
  parent_ref: FrozenRef | null;
  workspace_ref: FrozenRef;
  analysis_ref: FrozenRef;
  intents: DesignIntent[];
  selected_opportunity_ids: string[];
  constraint_set_ref?: FrozenRef | null;
  assumption_refs: FrozenRef[];
  required_decision_refs: FrozenRef[];
}

export interface SavedBriefPayload {
  status: 'DRAFT';
  brief: DesignBriefRevision;
  rejected_opportunities: OpportunityRejection[];
  change_reason?: string;
  input_hashes: Record<string, string>;
  artifact_ref: FrozenRef;
  idempotent_replay?: boolean;
}

export interface SiteIntelligenceResponse {
  project_id: string;
  status: 'AVAILABLE' | 'PARTIAL' | 'BLOCKED' | 'NOT_RUN' | 'STALE';
  analysis_status: string;
  latest_bundle_ref: FrozenRef | null;
  bundle_persisted: boolean;
  workspace_ref: FrozenRef;
  default_scope_ref: FrozenRef | null;
  scope_refs: Array<{
    scope_id: string;
    label: string;
    ref: FrozenRef;
    kind: string;
  }>;
  opportunity_ref: FrozenRef | null;
  opportunities: Opportunity[];
  input_hashes: Record<string, string>;
  latest_brief?: SavedBriefPayload | null;
  limitations: string[];
}
