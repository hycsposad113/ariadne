import { describe, expect, it } from 'vitest';
import {
  buildMapFigureMetadata,
  canExportMapFigure,
  selectMapScaleBar,
  type MapFigureContext,
} from './mapFigure';

const context: MapFigureContext = {
  projectId: 'rotterdam-m4h-pilot-project',
  workspace: {
    workspace_id: 'workspace-rotterdam-m4h',
    project_id: 'rotterdam-m4h-pilot-project',
    study_area_id: 'study-area-v5',
    revision: 6,
    status: 'DRAFT',
    feature_dispositions: [],
  },
  studyArea: { id: 'study-area-v5', status: 'CONFIRMED_FOR_EXPLORATION', revision: 1 },
  hasUnsavedChanges: false,
  sourcePackageRevision: 'spatial-r01',
  sourceSnapshotIds: ['snapshot-road-1', 'snapshot-building-1', 'snapshot-road-1'],
  sourceAttributions: [
    { publisher: 'PDOK / Kadaster', license: 'open data terms', dataset_snapshot_ids: ['snapshot-building-1'] },
    { publisher: 'OpenStreetMap contributors via Overpass API', license: 'ODbL 1.0', dataset_snapshot_ids: ['snapshot-road-1'] },
  ],
  buildingCount: 24,
  roadCount: 81,
  spatialZoneCount: 1,
  selectedFeatureIds: ['bag:building-42', 'bag:building-42'],
  activeSyntaxLayer: {
    layer_id: 'angular-integration-800m',
    title: 'Local-scale Angular Integration',
    scale: 'local',
    radius_m: 800,
    metric_key: 'integration',
    unit: 'dimensionless',
    calculation_status: 'COMPUTED',
    data_readiness: 'EXPLORATORY_800M_ONLY_SOURCE_COVERAGE_INSUFFICIENT',
    exploratory_only: true,
    formal_result_eligible: false,
    formula_version: 'turner-2007-angular-segment-v1',
    source_manifest_sha256: 'sha256:source',
    syntax_result_sha256: 'sha256:result',
    limitations: 'Coverage insufficient; exploratory only.',
    segment_values: {},
    statistics: { min: 0, max: 1, mean: 0.5, count: 0 },
    legend_breaks: [],
  },
  transform: { originX: 89100, originY: 435900, zoom: 0.5, panX: 400, panY: 300 },
  canvasWidth: 800,
  canvasHeight: 600,
  exportedAtUtc: '2026-09-24T12:00:00.000Z',
};

describe('map figure provenance and scope', () => {
  it('binds the exported map to current saved project, workspace, StudyArea and source result', () => {
    const metadata = buildMapFigureMetadata(context);

    expect(metadata.figureVersion).toBe('week4-analysis-map-v1');
    expect(metadata.workspace).toEqual({ id: 'workspace-rotterdam-m4h', revision: 6, status: 'DRAFT' });
    expect(metadata.studyArea).toEqual({ id: 'study-area-v5', revision: 1, status: 'CONFIRMED_FOR_EXPLORATION' });
    expect(metadata.sourceSnapshotIds).toEqual(['snapshot-building-1', 'snapshot-road-1']);
    expect(metadata.sourceAttributions).toEqual([
      { publisher: 'OpenStreetMap contributors via Overpass API', license: 'ODbL 1.0', dataset_snapshot_ids: ['snapshot-road-1'] },
      { publisher: 'PDOK / Kadaster', license: 'open data terms', dataset_snapshot_ids: ['snapshot-building-1'] },
    ]);
    expect(metadata.featureCounts).toEqual({ buildingsLoaded: 24, roadsLoaded: 81, spatialZones: 1 });
    expect(metadata.selectedFeatureIds).toEqual(['bag:building-42']);
    expect(metadata.analysisLayer).toMatchObject({
      id: 'angular-integration-800m',
      metricKey: 'integration',
      radiusMeters: 800,
      resultStatus: 'COMPUTED_EXPLORATORY',
      sourceManifestSha256: 'sha256:source',
      resultSha256: 'sha256:result',
    });
    expect(metadata.limitations.join(' ')).toMatch(/exploratory only/i);
    expect(metadata.limitations.join(' ')).toMatch(/not zero/i);
    expect(metadata.limitations.join(' ')).toMatch(/legal boundaries/i);
    expect(metadata.exportedAtUtc).toBe('2026-09-24T12:00:00.000Z');
  });

  it('blocks export when workspace is absent, belongs to another project or has a stale StudyArea', () => {
    expect(canExportMapFigure({ ...context, workspace: null })).toBe(false);
    expect(canExportMapFigure({
      ...context,
      workspace: { ...context.workspace!, project_id: 'other-project' },
    })).toBe(false);
    expect(canExportMapFigure({
      ...context,
      workspace: { ...context.workspace!, study_area_id: 'study-area-v4' },
    })).toBe(false);
    expect(canExportMapFigure({
      ...context,
      workspace: { ...context.workspace!, status: 'STALE' },
    })).toBe(false);
    expect(() => buildMapFigureMetadata({
      ...context,
      workspace: { ...context.workspace!, status: 'STALE' },
    })).toThrow(/saved workspace for the active StudyArea/i);
  });

  it('blocks export while the workspace has unsaved changes', () => {
    const dirtyContext = { ...context, hasUnsavedChanges: true };

    expect(canExportMapFigure(dirtyContext)).toBe(false);
    expect(() => buildMapFigureMetadata(dirtyContext)).toThrow(/unsaved workspace changes/i);
  });

  it('labels missing and blocked analysis as unavailable rather than zero', () => {
    const metadata = buildMapFigureMetadata({
      ...context,
      activeSyntaxLayer: null,
      sourcePackageRevision: null,
      sourceSnapshotIds: [],
      sourceAttributions: [],
    });

    expect(metadata.analysisLayer).toBeNull();
    expect(metadata.limitations.join(' ')).toMatch(/no active analysis result/i);
    expect(metadata.limitations.join(' ')).toMatch(/source completeness.*not.*inferred/i);
  });

  it('records the conceptual Exploration Design Area separately from StudyArea in export metadata', () => {
    const metadata = buildMapFigureMetadata({
      ...context,
      explorationDesignArea: {
        geometry: { type: 'Polygon', coordinates: [] },
        crs: 'EPSG:28992',
        area_m2: 12345,
        scope: 'EXPLORATION_DESIGN_AREA',
        status: 'DRAFT_PENDING_HUMAN_DECISION',
        author: 'designer',
        revision: 2,
      },
    });

    expect(metadata.explorationDesignArea).toEqual({
      scope: 'EXPLORATION_DESIGN_AREA',
      crs: 'EPSG:28992',
      areaM2: 12345,
      status: 'DRAFT_PENDING_HUMAN_DECISION',
      revision: 2,
    });
    expect(metadata.legend).toContainEqual({ label: 'Exploration Design Area (conceptual only)', color: '#facc15' });
    expect(metadata.limitations.join(' ')).toMatch(/not a legal design boundary/i);
  });

  it('chooses a scale bar distance that remains tied to the canvas metric transform', () => {
    const scale = selectMapScaleBar({ zoom: 0.5, canvasWidth: 800, sceneWidth: 1360 });

    expect(scale.distanceMeters).toBe(200);
    expect(scale.lengthPixels).toBeCloseTo(170);
    expect(scale.unit).toBe('m');
  });

  it('includes depthmapX quintile ranges and network mode in legend and analysis layer', () => {
    const metadata = buildMapFigureMetadata({
      ...context,
      activeSyntaxLayer: {
        ...context.activeSyntaxLayer!,
        radius_m: 800,
        segment_values: { s1: 0.1, s2: 0.5, s3: 0.9, s4: 1.3, s5: 1.8 },
      },
    });

    expect(metadata.analysisLayer?.networkMode).toBe('pedestrian (行人路網 800m)');
    // Legend should contain quintiles and uncomputed item
    expect(metadata.legend.some((entry) => entry.label.startsWith('Very Low (0-20%)'))).toBe(true);
    expect(metadata.legend.some((entry) => entry.label.startsWith('Very High (80-100%)'))).toBe(true);
    expect(metadata.legend).toContainEqual({
      label: 'Uncomputed / Excluded segments',
      color: '#64748b',
    });
  });
});
