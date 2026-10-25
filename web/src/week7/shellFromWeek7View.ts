import type { Building, FeatureDispositionType } from '../types';

export type Week7MapFeature = {
  id: string;
  scenario_id?: string;
  revision?: string;
  kind?: string;
  disposition?: string;
  geometry?: { type?: string; coordinates?: number[][][] };
  provenance?: string;
};

export type Week7PersistedView = {
  workspace_id?: string;
  revision?: string;
  scenario_id?: string;
  shell?: {
    authority_state?: string;
    study_area_id?: string | null;
    workspace_revision?: string;
  };
  map?: {
    revision?: string;
    scenario_id?: string;
    features?: Week7MapFeature[];
  };
};

export type Week7ShellApply = {
  authorityState: 'READY';
  studyAreaId: string | null;
  workspaceRevision: string;
  buildings: Building[];
  mapLabel: string;
};

const DISPOSITIONS = new Set<FeatureDispositionType>(['PRESERVE', 'EDITABLE', 'UNDECIDED']);

function isDisposition(value: string | undefined): value is FeatureDispositionType {
  return value !== undefined && DISPOSITIONS.has(value as FeatureDispositionType);
}

/** Apply a week7 view to the shipped shell only when the map revision is the head revision. */
export function shellFromWeek7View(view: Week7PersistedView): Week7ShellApply | null {
  const revision = view.revision;
  if (!revision || view.map?.revision !== revision) return null;
  if (view.shell?.authority_state !== 'READY') return null;
  if (view.shell.workspace_revision !== revision) return null;
  const buildings: Building[] = [];
  for (const feature of view.map?.features ?? []) {
    if (feature.scenario_id !== view.scenario_id || feature.revision !== revision) continue;
    if (!isDisposition(feature.disposition)) continue;
    const geometry = feature.geometry;
    if (!geometry || geometry.type !== 'Polygon' || !geometry.coordinates) continue;
    buildings.push({
      id: feature.id,
      geometry,
      disposition: feature.disposition,
      feature_kind: 'building',
      properties: { provenance: feature.provenance ?? 'FIXTURE_ONLY', kind: feature.kind ?? 'footprint' },
    });
  }
  const featureLabel = buildings[0] ? ` feature ${buildings[0].id}` : '';
  return {
    authorityState: 'READY',
    studyAreaId: view.shell.study_area_id ?? null,
    workspaceRevision: revision,
    buildings,
    mapLabel: `map revision ${revision}${featureLabel}`,
  };
}
