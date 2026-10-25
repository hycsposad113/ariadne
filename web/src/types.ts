export type FeatureDispositionType = 'PRESERVE' | 'EDITABLE' | 'UNDECIDED';

export interface Building {
  id: string;
  geometry: any;
  properties?: Record<string, any>;
  disposition: FeatureDispositionType;
  annotation?: string;
  source_artifact_id?: string;
  source_snapshot_id?: string;
  source_feature_id?: string;
  lineage_status?: string;
  feature_kind?: 'building';
}

export interface Segment {
  modes?: ("pedestrian" | "bicycle" | "motor_vehicle")[];
  origin?: "retained" | "transformed" | "new";
  width_m?: number;
  semantics_provenance?: string;
  id: string;
  geometry: {
    type: string;
    coordinates: number[][];
  };
  length_m: number;
  layer: number;
  highway?: string;
  feature_kind?: 'road';
  disposition?: FeatureDispositionType;
  annotation?: string;
  source_artifact_id?: string;
  source_snapshot_id?: string;
  source_feature_id?: string;
  lineage_status?: string;
}

export type SyntaxCalculationStatus =
  | 'COMPUTED'
  | 'NOT_COMPUTED'
  | 'NOT_COMPUTED_COVERAGE_BLOCKED'
  | 'NOT_COMPUTED_RUNTIME_BUDGET'
  | 'STALE'
  | 'BLOCKED';

export interface SyntaxLayer {
  layer_id: string;
  title: string;
  scale: 'local' | 'mid' | 'regional';
  radius_m: number;
  network_mode?: 'pedestrian' | 'bicycle' | 'motor_vehicle';
  metric_key: string;
  unit: string;
  calculation_status: SyntaxCalculationStatus;
  data_readiness: string;
  exploratory_only?: boolean;
  formal_result_eligible?: boolean;
  coverage_message?: string;
  formula_version?: string;
  source_manifest_sha256?: string;
  syntax_result_sha256?: string;
  study_area_sha256?: string;
  output_file_sha256?: string;
  network_policy_version?: string;
  method_of_record?: string;
  evidence_level?: string;
  download_envelope?: Record<string, unknown>;
  stability_result?: Record<string, unknown>;
  boundary_effect_limitation?: string;
  limitations: string;
  segment_values?: Record<string, number>;
  statistics?: {
    min?: number;
    max?: number;
    mean?: number;
    count?: number;
  } | null;
  legend_breaks?: number[];
}

export interface SyntaxLayerPlanEntry {
  layer_id: string;
  radius_m: number;
  network_mode?: SyntaxLayer['network_mode'];
  metric_key: string;
  calculation_status: SyntaxLayer['calculation_status'];
  data_readiness: string;
  exploratory_only?: boolean;
  formal_result_eligible?: boolean;
  segment_value_count?: number | null;
  limitations?: string;
  reason?: string;
}

export interface EvidenceCard {
  card_id: string;
  metric_key: string;
  metric_name: string;
  value: number;
  unit: string;
  confidence: string;
  source: string;
  limitations: string[];
  timestamp: string;
  status: string;
  crs: string;
  query_bounds: Array<Record<string, any>>;
  algorithm_version: string;
  input_sha256: string;
  output_sha256: string;
  source_package_id: string;
  source_package_revision: string;
  study_area_id: string;
  study_area_revision: number;
  study_area_geometry_sha256: string;
  source_feature_ids: string[];
  source_artifact_ids: string[];
  dataset_snapshot_ids: string[];
  parents: Array<Record<string, any>>;
  method_definition?: string;
  method_diagnostics?: Record<string, number>;
}

export interface EvidenceGap {
  topic: string;
  status: 'UNKNOWN' | 'BLOCKED';
  reason: string;
}

export interface SourceAttribution {
  publisher: string;
  license: string;
  dataset_snapshot_ids: string[];
}

export interface DraftNumericValue<Unit extends 'ratio' | 'm' = 'ratio' | 'm'> {
  value: number;
  unit: Unit;
  status: 'DRAFT_PENDING_HUMAN_DECISION';
}

export type DraftNumericInput<Unit extends 'ratio' | 'm' = 'ratio' | 'm'> = number | DraftNumericValue<Unit>;

export interface SpatialZone {
  zone_id: string;
  name: string;
  target_use: string;
  target_far?: DraftNumericInput<'ratio'>;
  target_coverage_ratio?: DraftNumericInput<'ratio'>;
  target_height_m?: DraftNumericInput<'m'>;
  geometry: any;
  status: 'DRAFT_PENDING_HUMAN_DECISION';
  author?: string;
  revision?: number;
  original_text?: string;
  program_demands?: string[];
  open_space_demands?: string[];
  draft_constraints?: string[];
  draft_preferences?: string[];
  notes?: string;
}

export type BriefPolygonPurpose = 'ZONE' | 'EXPLORATION_DESIGN_AREA';

export interface ExplorationDesignArea {
  geometry: any;
  crs: 'EPSG:28992';
  area_m2: number;
  scope: 'EXPLORATION_DESIGN_AREA';
  status: 'DRAFT_PENDING_HUMAN_DECISION';
  author: string;
  revision: number;
}

export interface WorkspaceRevision {
  workspace_id: string;
  revision: number;
  project_id: string;
  study_area_id: string;
  status: string;
  source_snapshot_ids?: string[];
  idempotency_key?: string;
  unverified_disposition_count?: number;
  unverified_spatial_zone_count?: number;
  historical_feature_dispositions?: WorkspaceRevision['feature_dispositions'];
  historical_spatial_brief?: {
    zones: SpatialZone[];
    exploration_design_area?: ExplorationDesignArea | null;
    status: string;
  };
  unverified_exploration_design_area_count?: number;
  payload_digest?: string;
  feature_dispositions: Array<{
    feature_id: string;
    feature_type?: string;
    feature_kind?: string;
    disposition: FeatureDispositionType;
    source_artifact_id?: string;
    source_snapshot_id?: string | null;
    source_feature_id?: string | null;
    annotation?: string;
  }>;
  spatial_brief?: {
    zones: SpatialZone[];
    exploration_design_area?: ExplorationDesignArea | null;
    status: string;
  };
  decision_summary?: Day1DecisionSummary | null;
  workspace_decision?: WorkspaceDecisionRecord | null;
}

export interface CriticResponse {
  critic_id: string;
  study_area_id: string;
  workspace_id: string;
  workspace_revision: number;
  evidence_refs: string[];
  observations: string[];
  design_hypotheses: string[];
  limitations: string[];
  next_questions: string[];
  provider_status?: string;
  provider_name?: string;
  provider_request_id?: string;
  provider_model?: string;
  provider_metadata?: Record<string, string | number | null>;
}

export interface DispositionsSummaryKind {
  preserve: string[];
  editable: string[];
  undecided: string[];
  counts: {
    preserve: number;
    editable: number;
    undecided: number;
    total: number;
  };
}

export interface WorkspaceDecisionRecord {
  id: string;
  project_id: string;
  target_id: string;
  target_type: string;
  target_version: string;
  target_geometry_sha256?: string | null;
  target_artifact_sha256?: string | null;
  target_payload_digest?: string | null;
  action: string;
  status: string;
  actor: string;
  actor_kind: string;
  actor_session_id?: string;
  reason: string;
  timestamp: string;
  decision_event_id?: string;
}

export interface Day1DecisionSummary {
  workspace_id: string;
  project_id: string;
  revision: number;
  payload_digest?: string;
  exploration_design_area?: {
    area_m2: number;
    crs?: string;
    geometry?: any;
    geometry_hash?: string;
    revision?: number;
    status?: string;
  } | null;
  dispositions: {
    buildings: DispositionsSummaryKind;
    roads: DispositionsSummaryKind;
  };
  zones: Array<{
    zone_id: string;
    name: string;
    target_use: string;
    area_m2?: number;
    target_far?: number | null;
    target_height_m?: number | null;
    draft_constraints?: string[];
    draft_preferences?: string[];
  }>;
  latest_decision?: WorkspaceDecisionRecord | null;
  is_current_revision?: boolean;
  is_stale_for_decision?: boolean;
  decision_status_label?: string;
}
