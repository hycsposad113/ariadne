import { describe, expect, it } from 'vitest';
import { buildSchematic3DFigureMetadata, canExportSchematic3DFigure, layoutSchematicLegend } from './schematicFigure';

describe('buildSchematic3DFigureMetadata', () => {
  it('reserves a row for the optional EDA legend before data limitations', () => {
    const layout = layoutSchematicLegend(7);
    const lastLegendBaseline = layout.legendStartY + (layout.legendRows - 1) * 36;

    expect(layout.legendRows).toBe(4);
    expect(layout.limitationsStartY).toBeGreaterThan(lastLegendBaseline);
    expect(layout.limitationsStartY - lastLegendBaseline).toBe(42);
  });

  it('binds a figure to the saved workspace, active StudyArea, and loaded source set', () => {
    const metadata = buildSchematic3DFigureMetadata({
      projectId: 'rotterdam-m4h-pilot-project',
      workspace: {
        workspace_id: 'workspace-rotterdam-m4h',
        revision: 6,
        project_id: 'rotterdam-m4h-pilot-project',
        study_area_id: 'study-area-v5',
        status: 'DRAFT',
        feature_dispositions: [],
      },
      studyArea: { id: 'study-area-v5', status: 'CONFIRMED_FOR_EXPLORATION', revision: 5 },
      hasUnsavedChanges: false,
      sourcePackageRevision: 'spatial-r01',
      sourceSnapshotIds: ['snapshot-road-1', 'snapshot-building-1'],
      buildingCount: 8,
      roadCount: 23,
      selectedFeatureIds: ['bag:building-42'],
      exportedAtUtc: '2026-09-24T12:00:00.000Z',
    });

    expect(metadata.figureVersion).toBe('week4-schematic-3d-v1');
    expect(metadata.projectId).toBe('rotterdam-m4h-pilot-project');
    expect(metadata.workspace).toEqual({ id: 'workspace-rotterdam-m4h', revision: 6, status: 'DRAFT' });
    expect(metadata.studyArea).toEqual({
      id: 'study-area-v5',
      revision: 5,
      status: 'CONFIRMED_FOR_EXPLORATION',
    });
    expect(metadata.sourcePackageRevision).toBe('spatial-r01');
    expect(metadata.sourceSnapshotIds).toEqual(['snapshot-building-1', 'snapshot-road-1']);
    expect(metadata.crs).toBe('EPSG:28992');
    expect(metadata.exportedAtUtc).toBe('2026-09-24T12:00:00.000Z');
    expect(metadata.featureCounts).toEqual({ buildingsLoaded: 8, roadsLoaded: 23, roadsRendered: 23 });
    expect(metadata.selectedFeatureIds).toEqual(['bag:building-42']);
    expect(metadata.limitations.join(' ')).toMatch(/schematic 14 m/i);
    expect(metadata.limitations.join(' ')).toMatch(/exploratory/i);
  });

  it('records a saved conceptual Exploration Design Area in the 3D figure metadata', () => {
    const metadata = buildSchematic3DFigureMetadata({
      projectId: 'rotterdam-m4h-pilot-project',
      workspace: { workspace_id: 'workspace-1', revision: 2, project_id: 'rotterdam-m4h-pilot-project', study_area_id: 'study-area-v5', status: 'DRAFT', feature_dispositions: [] },
      studyArea: { id: 'study-area-v5', status: 'CONFIRMED_FOR_EXPLORATION', revision: 5 },
      hasUnsavedChanges: false,
      sourcePackageRevision: 'spatial-r01',
      sourceSnapshotIds: ['snapshot-1'],
      buildingCount: 1,
      roadCount: 1,
      explorationDesignArea: {
        geometry: { type: 'Polygon', coordinates: [] },
        crs: 'EPSG:28992',
        area_m2: 54321,
        scope: 'EXPLORATION_DESIGN_AREA',
        status: 'DRAFT_PENDING_HUMAN_DECISION',
        author: 'designer',
        revision: 3,
      },
      selectedFeatureIds: [],
    });

    expect(metadata.explorationDesignArea).toEqual({
      scope: 'EXPLORATION_DESIGN_AREA',
      crs: 'EPSG:28992',
      areaM2: 54321,
      status: 'DRAFT_PENDING_HUMAN_DECISION',
      revision: 3,
    });
    expect(metadata.legend).toContainEqual({ label: 'Exploration Design Area (conceptual only)', color: '#facc15' });
    expect(metadata.limitations.join(' ')).toMatch(/not a legal design boundary/i);
  });

  it('reports the road-render cap instead of implying every loaded road is visible', () => {
    const metadata = buildSchematic3DFigureMetadata({
      projectId: 'rotterdam-m4h-pilot-project',
      workspace: { workspace_id: 'workspace-1', revision: 1, project_id: 'rotterdam-m4h-pilot-project', study_area_id: 'study-area-v5', status: 'DRAFT', feature_dispositions: [] },
      studyArea: { id: 'study-area-v5', status: 'CONFIRMED_FOR_EXPLORATION', revision: 5 },
      hasUnsavedChanges: false,
      sourcePackageRevision: null,
      sourceSnapshotIds: [],
      buildingCount: 2,
      roadCount: 503,
      selectedFeatureIds: [],
      exportedAtUtc: '2026-09-24T12:00:00.000Z',
    });

    expect(metadata.featureCounts).toEqual({ buildingsLoaded: 2, roadsLoaded: 503, roadsRendered: 500 });
    expect(metadata.limitations.join(' ')).toMatch(/500.*503/);
    expect(metadata.limitations.join(' ')).toMatch(/snapshot.*unavailable|no source snapshots/i);
  });

  it('rejects an unsaved or stale workspace whose StudyArea differs from the active one', () => {
    expect(() => buildSchematic3DFigureMetadata({
      projectId: 'rotterdam-m4h-pilot-project',
      workspace: { workspace_id: 'workspace-1', revision: 1, project_id: 'rotterdam-m4h-pilot-project', study_area_id: 'study-area-v4', status: 'STALE', feature_dispositions: [] },
      studyArea: { id: 'study-area-v5', status: 'CONFIRMED_FOR_EXPLORATION', revision: 5 },
      hasUnsavedChanges: false,
      sourcePackageRevision: 'spatial-r01',
      sourceSnapshotIds: ['snapshot-1'],
      buildingCount: 1,
      roadCount: 1,
      selectedFeatureIds: [],
    })).toThrow(/saved workspace for the active StudyArea/i);

    const matchingStaleContext = {
      projectId: 'rotterdam-m4h-pilot-project',
      workspace: { workspace_id: 'workspace-1', revision: 1, project_id: 'rotterdam-m4h-pilot-project', study_area_id: 'study-area-v5', status: 'STALE', feature_dispositions: [] },
      studyArea: { id: 'study-area-v5', status: 'CONFIRMED_FOR_EXPLORATION', revision: 5 },
      hasUnsavedChanges: false,
      sourcePackageRevision: 'spatial-r01',
      sourceSnapshotIds: ['snapshot-1'],
      buildingCount: 1,
      roadCount: 1,
      selectedFeatureIds: [],
    };

    expect(canExportSchematic3DFigure(matchingStaleContext)).toBe(false);
    expect(() => buildSchematic3DFigureMetadata(matchingStaleContext)).toThrow(/saved workspace for the active StudyArea/i);
  });

  it('blocks export while the workspace has unsaved changes', () => {
    const dirtyContext = {
      projectId: 'rotterdam-m4h-pilot-project',
      workspace: { workspace_id: 'workspace-1', revision: 1, project_id: 'rotterdam-m4h-pilot-project', study_area_id: 'study-area-v5', status: 'DRAFT', feature_dispositions: [] },
      studyArea: { id: 'study-area-v5', status: 'CONFIRMED_FOR_EXPLORATION', revision: 5 },
      sourcePackageRevision: 'spatial-r01',
      sourceSnapshotIds: ['snapshot-1'],
      buildingCount: 1,
      roadCount: 1,
      selectedFeatureIds: [],
      hasUnsavedChanges: true,
    };

    expect(canExportSchematic3DFigure(dirtyContext)).toBe(false);
    expect(() => buildSchematic3DFigureMetadata(dirtyContext)).toThrow(/unsaved workspace changes/i);
  });

  it('uses the renderer-observed road count when malformed loaded segments are skipped', () => {
    const metadata = buildSchematic3DFigureMetadata({
      projectId: 'rotterdam-m4h-pilot-project',
      workspace: { workspace_id: 'workspace-1', revision: 1, project_id: 'rotterdam-m4h-pilot-project', study_area_id: 'study-area-v5', status: 'DRAFT', feature_dispositions: [] },
      studyArea: { id: 'study-area-v5', status: 'CONFIRMED_FOR_EXPLORATION', revision: 5 },
      hasUnsavedChanges: false,
      sourcePackageRevision: 'spatial-r01',
      sourceSnapshotIds: ['snapshot-1'],
      buildingCount: 2,
      roadCount: 23,
      renderedRoadCount: 17,
      selectedFeatureIds: [],
      exportedAtUtc: '2026-09-24T12:00:00.000Z',
    });

    expect(metadata.featureCounts).toEqual({ buildingsLoaded: 2, roadsLoaded: 23, roadsRendered: 17 });
  });
});
