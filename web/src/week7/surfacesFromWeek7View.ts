import { formatFar } from '../utils/displayMetrics';
import type { EvidenceCard } from '../types';
import type { FigureWorkspaceCitation, SchematicFigureStudyArea } from '../utils/schematicFigure';

const PANEL_NAMES = ['map', 'model3d', 'dashboard', 'ai', 'chart', 'export'] as const;

export type Week7SurfaceCard = {
  evidence_id?: string;
  scenario_id?: string;
  revision?: string;
  source?: string;
  formula?: string;
  unit?: string;
  version?: string;
  limits?: string | string[];
  period?: string | null;
  validation_status?: string;
  numbers?: unknown;
  provenance?: string;
};

export type Week7SurfacePanel = {
  revision?: string;
  scenario_id?: string;
  far?: number | null;
  far_unit?: string | null;
  evidence_ids?: string[];
};

export type Week7SurfaceView = {
  workspace_ref?: { entity_id: string; revision: number };
  scenario_ref?: { entity_id: string; revision: number };
  workspace_id?: string;
  project_id?: string;
  scenario_id?: string;
  revision?: string;
  freshness?: string;
  evidence_status?: string;
  shell?: {
    study_area_id?: string | null;
    study_area_revision?: number | null;
    workspace_revision?: string;
  };
  map?: { revision?: string; scenario_id?: string };
  panels?: Partial<Record<(typeof PANEL_NAMES)[number], Week7SurfacePanel>>;
  cards?: Week7SurfaceCard[];
};

export type Week7BoundSurfaces = {
  revision: string;
  scenarioId: string;
  far: number | null;
  unit: string;
  dashboardLabel: string;
  chartsLabel: string;
  aiLabel: string;
  exportLabel: string;
  compareLabel: string;
  evidenceStatus: string;
  evidenceCards: EvidenceCard[];
  figureCitation: FigureWorkspaceCitation;
  figureStudyArea: SchematicFigureStudyArea | null;
};

function sameIds(left: string[] | undefined, right: string[] | undefined): boolean {
  const a = [...(left ?? [])].sort();
  const b = [...(right ?? [])].sort();
  return a.length === b.length && a.every((item, index) => item === b[index]);
}

function oneNumber(numbers: unknown): number | null {
  if (typeof numbers === 'number' && Number.isFinite(numbers)) return numbers;
  if (Array.isArray(numbers) && numbers.length === 1 && typeof numbers[0] === 'number' && Number.isFinite(numbers[0])) {
    return numbers[0];
  }
  return null;
}

function limitLines(limits: string | string[] | undefined): string[] {
  if (Array.isArray(limits)) return limits.filter((item): item is string => typeof item === 'string');
  if (typeof limits === 'string' && limits.trim()) return [limits];
  return [];
}

/** Recompute visible surface labels from one persisted head. Disagreeing panels bind nothing. */
export function surfacesFromWeek7View(view: Week7SurfaceView): Week7BoundSurfaces | null {
  if (view.workspace_ref && view.scenario_ref) {
    const ws = view.workspace_ref;
    const scenario = view.scenario_ref;
    const revision = `${ws.entity_id}@${ws.revision}/${scenario.entity_id}@${scenario.revision}`;
    if (view.revision !== revision || view.workspace_id !== ws.entity_id || view.scenario_id !== scenario.entity_id || !view.project_id) return null;
    for (const name of PANEL_NAMES) {
      const panel = view.panels?.[name];
      if (panel?.revision !== revision || panel.scenario_id !== scenario.entity_id) return null;
    }
    const far = view.panels?.dashboard?.far ?? null;
    const unit = view.panels?.dashboard?.far_unit ?? '';
    const label = (surface: string) => `${surface} ${revision} FAR ${far === null || !Number.isFinite(far) ? 'unavailable' : formatFar(far)} ${unit} · ${view.freshness ?? 'UNKNOWN'}`;
    return { revision, scenarioId: scenario.entity_id, far, unit,
      dashboardLabel: label('dashboard'), chartsLabel: label('charts'), aiLabel: label('AI'),
      exportLabel: label('export'), compareLabel: label('compare'), evidenceStatus: view.evidence_status ?? 'UNKNOWN',
      evidenceCards: [], figureCitation: { workspace_id: ws.entity_id, revision, project_id: view.project_id,
        study_area_id: view.shell?.study_area_id ?? '', status: view.freshness ?? 'UNKNOWN', feature_dispositions: [] },
      figureStudyArea: null };
  }
  const revision = view.revision;
  const scenarioId = view.scenario_id;
  const projectId = view.project_id;
  const workspaceId = view.workspace_id;
  if (!revision || !scenarioId || !projectId || !workspaceId) return null;
  if (view.map?.revision !== revision || view.map.scenario_id !== scenarioId) return null;
  if (view.shell?.workspace_revision !== revision) return null;
  const freshness = view.freshness === 'stale' ? 'STALE' : view.freshness === 'current' ? 'current' : null;
  if (!freshness || !view.evidence_status) return null;
  const panels = view.panels;
  if (!panels) return null;
  const head = panels.dashboard;
  if (!head || head.revision !== revision || head.scenario_id !== scenarioId) return null;
  for (const name of PANEL_NAMES) {
    const panel = panels[name];
    if (!panel || panel.revision !== revision || panel.scenario_id !== scenarioId) return null;
    if (panel.far !== head.far || panel.far_unit !== head.far_unit) return null;
    if (!sameIds(panel.evidence_ids, head.evidence_ids)) return null;
  }
  for (const card of view.cards ?? []) {
    if (card.revision !== revision || card.scenario_id !== scenarioId) return null;
    if (!card.evidence_id || !card.validation_status || !card.source || !card.unit) return null;
  }
  const far = typeof head.far === 'number' ? head.far : null;
  const unit = head.far_unit ?? '';
  const cardIds = (view.cards ?? []).map(card => card.evidence_id).filter((id): id is string => Boolean(id)).sort();
  const cardSuffix = cardIds.length ? ` card ${cardIds.join(' ')}` : '';
  const label = (surface: string) => ` ${surface} revision ${revision} scenario ${scenarioId} far ${far === null || !Number.isFinite(far) ? 'unavailable' : formatFar(far)} ${unit}${cardSuffix}`.trim();
  const studyAreaId = view.shell?.study_area_id ?? '';
  const studyAreaRevision = view.shell?.study_area_revision;
  const hasStudyAreaRevision = typeof studyAreaRevision === 'number' && Number.isInteger(studyAreaRevision);
  const evidenceCards: EvidenceCard[] = [];
  if (hasStudyAreaRevision) {
    for (const card of view.cards ?? []) {
      const value = oneNumber(card.numbers);
      if (value === null || !card.evidence_id || !card.validation_status || !card.source || !card.unit) continue;
      evidenceCards.push({
        card_id: card.evidence_id,
        metric_key: card.evidence_id,
        metric_name: card.source,
        value,
        unit: card.unit,
        confidence: card.provenance || 'FIXTURE_ONLY',
        source: card.source,
        limitations: limitLines(card.limits),
        timestamp: card.period || '',
        status: card.validation_status,
        crs: '',
        query_bounds: [],
        algorithm_version: card.version || revision,
        input_sha256: '',
        output_sha256: '',
        source_package_id: '',
        source_package_revision: revision,
        study_area_id: studyAreaId,
        study_area_revision: studyAreaRevision,
        study_area_geometry_sha256: '',
        source_feature_ids: [],
        source_artifact_ids: [],
        dataset_snapshot_ids: [],
        parents: [],
        method_definition: card.formula || '',
      });
    }
  }
  return {
    revision,
    scenarioId,
    far,
    unit,
    dashboardLabel: label('dashboard'),
    chartsLabel: label('charts'),
    aiLabel: label('ai'),
    exportLabel: label('export'),
    compareLabel: label('compare'),
    evidenceStatus: view.evidence_status,
    evidenceCards,
    figureCitation: {
      workspace_id: workspaceId,
      revision,
      project_id: projectId,
      study_area_id: studyAreaId,
      status: freshness,
      feature_dispositions: [],
    },
    figureStudyArea: hasStudyAreaRevision && studyAreaId
      ? { id: studyAreaId, status: freshness, revision: studyAreaRevision }
      : null,
  };
}
